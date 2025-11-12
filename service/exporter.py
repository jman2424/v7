"""
Export helpers for CSV/JSON.

- Leads to CSV/JSON
- Analytics summary to CSV/JSON
- Utility returns bytes; routes can stream or write to file
"""

from __future__ import annotations
import csv
import io
import json
from typing import Any, Dict, Iterable, List, Tuple


# ---- JSON ----

def to_json_bytes(obj: Any, *, pretty: bool = False) -> bytes:
    if pretty:
        return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# ---- CSV ----

def leads_to_csv_bytes(leads: Iterable[Dict[str, Any]]) -> bytes:
    """
    Expected lead shape:
      {id, name, phone, email, status, tags[], created_at, updated_at}
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "name", "phone", "email", "status", "tags", "created_at", "updated_at"])
    for l in leads:
        writer.writerow([
            l.get("id") or l.get("_id") or "",
            l.get("name") or "",
            l.get("phone") or "",
            l.get("email") or "",
            l.get("status") or "",
            ",".join(l.get("tags") or []),
            l.get("created_at") or "",
            l.get("updated_at") or "",
        ])
    return buf.getvalue().encode("utf-8")


def analytics_summary_to_csv_bytes(summary: Dict[str, Any]) -> bytes:
    """
    Flattens analytics summary:
      { totals: {...}, top_intents: [{key,count}], top_items: [{key,count}] }
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["metric", "key", "value"])

    totals = summary.get("totals") or {}
    for k, v in totals.items():
        writer.writerow(["total", k, v])

    for row in summary.get("top_intents") or []:
        writer.writerow(["top_intent", row.get("key"), row.get("count")])

    for row in summary.get("top_items") or []:
        writer.writerow(["top_item", row.get("key"), row.get("count")])

    return buf.getvalue().encode("utf-8")
