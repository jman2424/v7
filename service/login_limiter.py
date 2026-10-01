"""Shared account attempt bounds without storing email addresses or IPs."""

from __future__ import annotations

import hashlib
import hmac
import json

from flask import current_app

from service import session_store


class LoginThrottled(ValueError):
    def __init__(self, retry_after: int) -> None:
        super().__init__('try_again_later')
        self.retry_after = retry_after


class LoginAttemptLimiter:
    """Reserve password/MFA checks atomically across addresses and workers."""

    def __init__(self, *, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max(1, int(max_attempts))
        self.window_seconds = max(1, int(window_seconds))

    @staticmethod
    def key(*, client_address: str = '', tenant: str, identifier: str) -> str:
        # Address throttling is separate. Account bounds must survive a change
        # of address, worker or browser; the subject remains tenant-scoped.
        subject = json.dumps([tenant.strip().upper(), identifier.strip().lower()], separators=(',', ':'))
        return hmac.new(current_app.secret_key.encode(), subject.encode(), hashlib.sha256).hexdigest()

    @classmethod
    def identity_key(cls, user: dict) -> str:
        platform = bool({'platform_admin', 'admin'}.intersection(user.get('roles', [])))
        return cls.key(tenant='' if platform else user.get('tenant', ''), identifier=user['email'])

    def retry_after(self, key: str) -> int:
        return session_store.login_retry_after(key, max_attempts=self.max_attempts, window_seconds=self.window_seconds)

    def begin(self, key: str) -> str:
        attempt, retry_after = session_store.reserve_login_attempt(
            key, max_attempts=self.max_attempts, window_seconds=self.window_seconds)
        if retry_after:
            raise LoginThrottled(retry_after)
        if not attempt:
            raise RuntimeError('Could not reserve a sign-in attempt')
        return attempt

    def record_failure(self, key: str) -> None:
        self.begin(key)

    def release(self, key: str, attempt: str, *, transaction=None) -> None:
        session_store.release_login_attempt(key, attempt, transaction=transaction)

    def fail(self, key: str, attempt: str, *, transaction=None) -> None:
        session_store.finish_login_failure(key, attempt, transaction=transaction)

    def reset(self, key: str, *, transaction=None) -> None:
        session_store.reset_login_failures(key, transaction=transaction)
