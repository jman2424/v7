"""Tenant-scoped PostgreSQL repository for V7 business documents.

The caller must establish the account's tenant access before constructing this
repository. A validated tenant key is a scope, not an authorization decision.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timezone
from typing import Any, Iterator, Mapping

from service.session_store import postgres_connection


_TENANT_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\Z")


class TenantDocumentStorageError(RuntimeError):
    """A database operation failed without exposing connection or record details."""


def _valid_tenant(value: str) -> str:
    if not isinstance(value, str) or not _TENANT_KEY.fullmatch(value) or value.lower() == "versions":
        raise ValueError("invalid_tenant")
    return value


def _valid_filename(value: str) -> str:
    if not isinstance(value, str) or not _FILENAME.fullmatch(value):
        raise ValueError("invalid_filename")
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _jsonb(value: Any) -> Any:
    try:
        from psycopg.types.json import Jsonb
    except ImportError:
        raise TenantDocumentStorageError("PostgreSQL driver unavailable") from None
    return Jsonb(value, dumps=_json_dumps)


class PostgresBusinessDocuments:
    """Access exactly one tenant with the restricted V7 database login.

    Passing a tenant key here never grants tenant access; callers must use their
    existing server-side account and tenant authorization first. The connection
    comes from the shared, restricted server transaction helper.
    """

    __slots__ = ("_tenant_key", "_active_connection")

    def __init__(self, authorized_tenant_key: str) -> None:
        self._tenant_key = _valid_tenant(authorized_tenant_key)
        self._active_connection: ContextVar[Any | None] = ContextVar(
            f"v7_business_documents_{id(self)}", default=None
        )

    @property
    def tenant_key(self) -> str:
        return self._tenant_key

    def exists(self) -> bool:
        with self._connection() as connection:
            return connection.execute(
                "SELECT 1 FROM v7_private.tenants WHERE tenant = %s",
                (self.tenant_key,),
            ).fetchone() is not None

    @contextmanager
    def _transaction(self) -> Iterator[Any]:
        with postgres_connection(self.tenant_key) as connection:
            tables = connection.execute(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                "c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'v7_private' "
                "AND c.relname IN ('tenants', 'business_documents', 'document_versions')"
            ).fetchall()
            if (len(tables) != 3 or
                    any(not row[1] or not row[2] or row[3] for row in tables)):
                raise TenantDocumentStorageError("Restricted V7 business tables required")
            if any(connection.execute(
                "SELECT has_table_privilege(current_user, %s, 'TRUNCATE')",
                (f"v7_private.{table}",),
            ).fetchone()[0] for table in ("tenants", "business_documents", "document_versions")):
                raise TenantDocumentStorageError("Restricted V7 business tables required")
            yield connection

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        active = self._active_connection.get()
        if active is not None:
            yield active
        else:
            with self._transaction() as connection:
                yield connection

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Keep revision checks and writes in one tenant-locked transaction."""
        if self._active_connection.get() is not None:
            raise TenantDocumentStorageError("Nested tenant write lock")
        with self._transaction() as connection:
            tenant = connection.execute(
                "SELECT tenant FROM v7_private.tenants WHERE tenant = %s FOR UPDATE",
                (self.tenant_key,),
            ).fetchone()
            if tenant is None:
                raise FileNotFoundError(self.tenant_key)
            token = self._active_connection.set(connection)
            try:
                yield
            finally:
                self._active_connection.reset(token)

    def create_tenant(self, documents: Mapping[str, Any], *, owner_key: str | None = None) -> None:
        """Create the tenant and its initial JSON documents in one transaction."""
        prepared = [(_valid_filename(name), _jsonb(value)) for name, value in documents.items()]
        # Reject non-JSON data before opening a transaction.
        for value in documents.values():
            _json_dumps(value)
        with self._connection() as connection:
            connection.execute("INSERT INTO v7_private.tenants (tenant) VALUES (%s)", (self.tenant_key,))
            for filename, payload in prepared:
                connection.execute(
                    "INSERT INTO v7_private.business_documents (tenant, filename, payload) VALUES (%s, %s, %s)",
                    (self.tenant_key, filename, payload),
                )
            # Workspace documents and ownership must appear together. A failed
            # insert rolls back the whole PostgreSQL transaction.
            connection.execute(
                "INSERT INTO v7_private.managed_businesses (tenant, owner) VALUES (%s, %s)",
                (self.tenant_key, owner_key),
            )

    def read_document(self, filename: str) -> Any:
        filename = _valid_filename(filename)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload FROM v7_private.business_documents WHERE tenant = %s AND filename = %s",
                (self.tenant_key, filename),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(filename)
        return row[0]

    def list_documents(self) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT filename FROM v7_private.business_documents WHERE tenant = %s ORDER BY filename",
                (self.tenant_key,),
            ).fetchall()
        return [row[0] for row in rows]

    def write_document(self, filename: str, payload: Any, *, snapshot: bool = True) -> str:
        """Write JSON and preserve the day's pre-write documents atomically.

        Returns the historical ``YYYY-MM-DD/tenant/filename`` snapshot path when
        a previous version of this JSON file exists, otherwise an empty string.
        """
        filename = _valid_filename(filename)
        _json_dumps(payload)
        now = datetime.now(timezone.utc)
        day = now.date()
        version_path = ""
        with self._connection() as connection:
            # All writers for this tenant take the same row lock before checking
            # snapshots or updating a document, including concurrent workers.
            tenant = connection.execute(
                "SELECT tenant FROM v7_private.tenants WHERE tenant = %s FOR UPDATE",
                (self.tenant_key,),
            ).fetchone()
            if tenant is None:
                raise FileNotFoundError(self.tenant_key)
            if snapshot:
                existing_day = connection.execute(
                    "SELECT 1 FROM v7_private.document_versions WHERE tenant = %s AND day = %s LIMIT 1",
                    (self.tenant_key, day),
                ).fetchone()
                if existing_day is None:
                    connection.execute(
                        """INSERT INTO v7_private.document_versions (tenant, day, filename, payload)
                           SELECT tenant, %s, filename, payload
                           FROM v7_private.business_documents
                           WHERE tenant = %s AND filename LIKE '%%.json'""",
                        (day, self.tenant_key),
                    )
                    connection.execute(
                        """INSERT INTO v7_private.document_versions (tenant, day, filename, payload)
                           VALUES (%s, %s, '_snapshot.json', %s)""",
                        (self.tenant_key, day, _jsonb({
                            "tenant": self.tenant_key,
                            "created_at": now.isoformat().replace("+00:00", "Z"),
                            "source": "v7_private.business_documents",
                        })),
                    )
                previous = connection.execute(
                    """INSERT INTO v7_private.document_versions (tenant, day, filename, payload)
                       SELECT tenant, %s, filename, payload
                       FROM v7_private.business_documents
                       WHERE tenant = %s AND filename = %s AND filename LIKE '%%.json'
                       ON CONFLICT (tenant, day, filename) DO NOTHING
                       RETURNING filename""",
                    (day, self.tenant_key, filename),
                ).fetchone()
                if previous is not None:
                    version_path = f"{day.isoformat()}/{self.tenant_key}/{filename}"
                elif filename.endswith(".json"):
                    version = connection.execute(
                        """SELECT 1 FROM v7_private.document_versions
                           WHERE tenant = %s AND day = %s AND filename = %s""",
                        (self.tenant_key, day, filename),
                    ).fetchone()
                    if version is not None:
                        version_path = f"{day.isoformat()}/{self.tenant_key}/{filename}"
            connection.execute(
                """INSERT INTO v7_private.business_documents (tenant, filename, payload)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (tenant, filename) DO UPDATE SET payload = EXCLUDED.payload""",
                (self.tenant_key, filename, _jsonb(payload)),
            )
        return version_path

    def list_version_days(self) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT DISTINCT day FROM v7_private.document_versions WHERE tenant = %s ORDER BY day",
                (self.tenant_key,),
            ).fetchall()
        return [row[0].isoformat() for row in rows]

    def read_version(self, day: str, filename: str) -> Any:
        filename = _valid_filename(filename)
        try:
            parsed_day = date.fromisoformat(day)
        except (TypeError, ValueError):
            raise ValueError("invalid_snapshot") from None
        if parsed_day.isoformat() != day:
            raise ValueError("invalid_snapshot")
        with self._transaction() as connection:
            row = connection.execute(
                """SELECT payload FROM v7_private.document_versions
                   WHERE tenant = %s AND day = %s AND filename = %s""",
                (self.tenant_key, parsed_day, filename),
            ).fetchone()
        if row is None:
            raise FileNotFoundError(f"{day}/{self.tenant_key}/{filename}")
        return row[0]
