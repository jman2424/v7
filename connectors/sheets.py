"""
Google Sheets connector.

Responsibilities:
- Append analytics events
- Read/write catalog exports
- Respect rate limits & exponential backoff
- Minimal dependencies (urllib only)
- Optional usage: if creds not set, calls are no-ops

Env:
  SHEETS_API_URL  (custom proxy or direct)
  SHEETS_API_KEY
  SHEETS_ANALYTICS_SHEET_ID
  SHEETS_EXPORT_SHEET_ID
"""

from __future__ import annotations
import json
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _json(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


@dataclass
class SheetsClient:
    api_url: str
    api_key: str
    analytics_sheet: Optional[str] = None
    export_sheet: Optional[str] = None
    max_retries: int = 3
    backoff_base: float = 0.5

    # -------- factory --------
    @classmethod
    def from_env(cls) -> "SheetsClient":
        return cls(
            api_url=os.getenv("SHEETS_API_URL", "https://sheets.googleapis.com/v4/spreadsheets"),
            api_key=os.getenv("SHEETS_API_KEY", ""),
            analytics_sheet=os.getenv("SHEETS_ANALYTICS_SHEET_ID"),
            export_sheet=os.getenv("SHEETS_EXPORT_SHEET_ID"),
        )

    # -------- internal HTTP helper --------
    def _req(self, url: str, payload: Dict[str, Any]) -> bool:
        data = _json(payload)
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=8) as r:
                    if 200 <= r.status < 300:
                        return True
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 503):
                    delay = self.backoff_base * (2 ** (attempt - 1)) + random.random() * 0.2
                    time.sleep(delay)
                    continue
                raise
            except Exception:
                delay = self.backoff_base * (2 ** (attempt - 1))
                time.sleep(delay)
        return False

    # -------- public API --------
    def append_event(self, tenant: str, event: Dict[str, Any]) -> bool:
        """
        Append one analytics event row.
        """
        if not (self.api_url and self.api_key and self.analytics_sheet):
            return False
        url = f"{self.api_url}/{self.analytics_sheet}/values/Events:append?valueInputOption=RAW"
        row = [
            time.strftime("%Y-%m-%d %H:%M:%S"),
            tenant,
            event.get("type"),
            json.dumps(event, ensure_ascii=False),
        ]
        payload = {"values": [row]}
        return self._req(url, payload)

    def export_catalog(self, tenant: str, catalog: Dict[str, Any]) -> bool:
        """
        Upload entire catalog (flattened) into export sheet.
        """
        if not (self.api_url and self.api_key and self.export_sheet):
            return False
        rows: List[List[Any]] = []
        for cat in catalog.get("categories", []):
            cname = cat.get("name")
            for item in (cat.get("items") or []):
                rows.append([
                    tenant,
                    cname,
                    item.get("name"),
                    item.get("price"),
                    "Y" if item.get("in_stock") else "N",
                    ",".join(item.get("tags") or []),
                ])
        payload = {"values": rows}
        url = f"{self.api_url}/{self.export_sheet}/values/Catalog:append?valueInputOption=RAW"
        return self._req(url, payload)

    def import_catalog(self, tenant: str) -> Optional[Dict[str, Any]]:
        """
        (Optional) Read back export sheet into structured catalog.
        Assumes the same column order as export_catalog().
        """
        if not (self.api_url and self.api_key and self.export_sheet):
            return None
        try:
            url = f"{self.api_url}/{self.export_sheet}/values/Catalog?majorDimension=ROWS"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.api_key}"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
            values = data.get("values", [])[1:]  # skip header
            catalog: Dict[str, Any] = {"version": 1, "categories": []}
            by_cat: Dict[str, List[Dict[str, Any]]] = {}
            for row in values:
                if len(row) < 6:
                    continue
                _, cat, name, price, stock, tags = row
                by_cat.setdefault(cat, []).append({
                    "name": name,
                    "price": float(price or 0),
                    "in_stock": stock.upper().startswith("Y"),
                    "tags": [t.strip() for t in tags.split(",") if t.strip()],
                })
            for cname, items in by_cat.items():
                catalog["categories"].append({"name": cname, "items": items})
            return catalog
        except Exception:
            return None
