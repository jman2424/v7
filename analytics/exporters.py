"""
Analytics exporters — CSV and Google Sheets bulk.

Contracts:
- export_csv(rows, path) -> str
    rows: Iterable[Mapping[str, Any]]  (flat dicts)
    path: filesystem path to write CSV
    returns: path

- export_to_sheets(rows, sheets_ctx) -> dict
    rows: Iterable[Mapping[str, Any]]
    sheets_ctx: an object with method append_rows(sheet_name, header, rows)
                (provided by connectors/sheets.py or an adapter in routes)
    returns: {"sheet": str, "written": int}

Notes:
- Keep exports tolerant to missing keys; union of all keys becomes CSV header.
- No imports from Flask here; pure library.
"""

from __future__ import annotations
import csv
from typing import Any, Iterable, Mapping, Set, List


def _collect_header(rows: Iterable[Mapping[str, Any]]) -> List[str]:
    keyset: Set[str] = set()
    snapshot = []
    for r in rows:
        snapshot.append(r)
        keyset.update(map(str, r.keys()))
    header = sorted(keyset)
    return header, snapshot


def export_csv(rows: Iterable[Mapping[str, Any]], path: str) -> str:
    header, snapshot = _collect_header(rows)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for r in snapshot:
            w.writerow({k: r.get(k, "") for k in header})
    return path


def export_to_sheets(
    rows: Iterable[Mapping[str, Any]],
    sheets_ctx: Any,
    sheet_name: str = "analytics_events",
    include_header: bool = True,
) -> dict:
    header, snapshot = _collect_header(rows)
    values = []
    if include_header:
        values.append(header)
    for r in snapshot:
        values.append([r.get(k, "") for k in header])

    # Expect sheets_ctx to implement: append_rows(sheet_name, rows: List[List[str]])
    written = sheets_ctx.append_rows(sheet_name, values)
    return {"sheet": sheet_name, "written": written}
