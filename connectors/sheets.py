"""
Google Sheets connector (v7-aware).

Responsibilities:
- Append analytics events
- Read/write catalog exports
- Respect rate limits & exponential backoff
- Minimal dependencies (urllib only)
- Optional usage: if creds not set, calls are no-ops

Env (any of these may be used):
  SHEETS_API_URL               (custom proxy or direct, default Google Sheets API)
  SHEETS_API_KEY               (API key or bearer token for proxy)
  SHEETS_ANALYTICS_SHEET_ID    (spreadsheet ID for analytics; falls back to GOOGLE_SHEETS_ID)
  SHEETS_EXPORT_SHEET_ID       (spreadsheet ID for catalog export; falls back to GOOGLE_SHEETS_ID)

New-style envs (preferred in your stack):
  GOOGLE_API_KEY               (used if SHEETS_API_KEY missing)
  GOOGLE_SHEETS_ID             (used if SHEETS_*_SHEET_ID missing)
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
        api_url = os.getenv(
            "SHEETS_API_URL",
            "https://sheets.googleapis.com/v4/spreadsheets",
        )

        # Prefer SHEETS_API_KEY, fall back to GOOGLE_API_KEY
        api_key = os.getenv("SHEETS_API_KEY") or os.getenv("GOOGLE_API_KEY", "")

        # Prefer explicit SHEETS_* ids, fall back to single GOOGLE_SHEETS_ID
        google_sheet_id = os.getenv("GOOGLE_SHEETS_ID")
        analytics_sheet = os.getenv("SHEETS_ANALYTICS_SHEET_ID") or google_sheet_id
        export_sheet = os.getenv("SHEETS_EXPORT_SHEET_ID") or google_sheet_id

        return cls(
            api_url=api_url,
            api_key=api_key,
            analytics_sheet=analytics_sheet,
            export_sheet=export_sheet,
        )

    # -------- internal HTTP helper --------
    def _req(self, url: str, payload: Dict[str, Any]) -> bool:
        if not self.api_key:
            # Sheets integration disabled
            return False

        data = _json(payload)
        for attempt in range(1, self.max_retries + 1):
            try:
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={
                        "Content-Type": "application/json",
                        # For a custom proxy this is often correct.
                        # For direct Google Sheets with an API key, you may instead
                        # want to pass ?key=... in the URL and drop Authorization.
                        "Authorization": f"Bearer {self.api_key}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=8) as r:
                    if 200 <= r.status < 300:
                        return True
            except urllib.error.HTTPError as e:
                # retry only on transient errors
                if e.code in (429, 500, 503):
                    delay = self.backoff_base * (2 ** (attempt - 1)) + random.random() * 0.2
                    time.sleep(delay)
                    continue
                # other HTTP errors: give up
                return False
            except Exception:
                # network or timeout: exponential backoff
                delay = self.backoff_base * (2 ** (attempt - 1))
                time.sleep(delay)
        return False

    # -------- public API: analytics --------
    def append_event(self, tenant: str, event: Dict[str, Any]) -> bool:
        """
        Append one analytics event row.

        Sheet layout (Events sheet):
          A: timestamp (iso)
          B: tenant
          C: type
          D: full JSON blob
        """
        if not (self.api_url and self.api_key and self.analytics_sheet):
            return False

        # Range "Events" tab; adapt if you want a different sheet name.
        url = f"{self.api_url}/{self.analytics_sheet}/values/Events!A:D:append?valueInputOption=RAW"
        row = [
            time.strftime("%Y-%m-%d %H:%M:%S"),
            tenant,
            event.get("type"),
            json.dumps(event, ensure_ascii=False),
        ]
        payload = {"values": [row]}
        return self._req(url, payload)

    # -------- public API: catalog export (v7-aware) --------
    def export_catalog(self, tenant: str, catalog: Dict[str, Any]) -> bool:
        """
        Upload entire catalog (flattened) into export sheet.

        Supports both legacy and v7 shapes:

        Legacy:
          {
            "categories": [
              {"name": "Chicken", "items": [
                  {"name": "Breast", "price": 5.99, "in_stock": True, "tags": [...]},
              ]}
            ]
          }

        V7 (Tariq):
          {
            "product_catalog": [
              {"name": "POULTRY", "items": [
                  {"name": "Whole Chicken", "price_str": "£4.50", "subcategory": "Fresh", "stock": "In Stock"},
              ]}
            ]
          }

        Sheet layout (Catalog sheet):
          A: tenant
          B: category
          C: subcategory
          D: name
          E: price_str
          F: stock
        """
        if not (self.api_url and self.api_key and self.export_sheet):
            return False

        rows: List[List[Any]] = []

        # 1) v7 shape: product_catalog
        pc = catalog.get("product_catalog")
        if isinstance(pc, list):
            for cat in pc:
                cat_name = (cat or {}).get("name") or ""
                items = (cat or {}).get("items") or []
                for item in items:
                    if not item:
                        continue
                    name = item.get("name") or ""
                    subcat = item.get("subcategory") or ""
                    # price_str is already formatted "£x.xx", fallback to price if needed
                    price_str = item.get("price_str")
                    if price_str is None and "price" in item:
                        try:
                            price_str = f"£{float(item['price']):.2f}"
                        except Exception:
                            price_str = str(item["price"])
                    price_str = price_str or ""
                    stock = item.get("stock") or ""
                    rows.append([
                        tenant,
                        cat_name,
                        subcat,
                        name,
                        price_str,
                        stock,
                    ])

        # 2) legacy shape: categories (fallback)
        elif isinstance(catalog.get("categories"), list):
            for cat in catalog["categories"]:
                cat_name = (cat or {}).get("name") or ""
                items = (cat or {}).get("items") or []
                for item in items:
                    if not item:
                        continue
                    name = item.get("name") or ""
                    price = item.get("price")
                    try:
                        price_str = f"£{float(price):.2f}" if price is not None else ""
                    except Exception:
                        price_str = str(price) if price is not None else ""
                    stock = "Y" if item.get("in_stock") else "N"
                    tags = ",".join(item.get("tags") or [])
                    # we keep tags in stock column only if you still care; safer: ignore tags
                    rows.append([
                        tenant,
                        cat_name,
                        "",           # no subcategory in old shape
                        name,
                        price_str,
                        stock,
                    ])

        if not rows:
            return False

        payload = {"values": rows}
        url = f"{self.api_url}/{self.export_sheet}/values/Catalog!A:F:append?valueInputOption=RAW"
        return self._req(url, payload)

    # -------- public API: catalog import (v7 shape) --------
    def import_catalog(self, tenant: str) -> Optional[Dict[str, Any]]:
        """
        Read back export sheet into structured v7 catalog.

        Expects same column order as export_catalog():

          A: tenant
          B: category
          C: subcategory
          D: name
          E: price_str
          F: stock

        Returns:
          {
            "product_catalog": [
              {
                "name": "POULTRY",
                "items": [
                  {"name": "...", "price_str": "£x.xx", "subcategory": "...", "stock": "..."},
                ]
              },
              ...
            ]
          }
        """
        if not (self.api_url and self.api_key and self.export_sheet):
            return None

        try:
            url = f"{self.api_url}/{self.export_sheet}/values/Catalog!A:F?majorDimension=ROWS"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))

            values = data.get("values", [])
            if not values or len(values) < 2:
                return None

            # First row might be header; detect quickly.
            rows = values
            header = [c.strip().lower() for c in rows[0]]
            if header[:6] == ["tenant", "category", "subcategory", "name", "price_str", "stock"]:
                rows = rows[1:]  # skip header

            by_cat: Dict[str, List[Dict[str, Any]]] = {}

            for row in rows:
                if len(row) < 6:
                    continue
                row_tenant, cat, subcat, name, price_str, stock = (row + [""] * 6)[:6]

                # If multi-tenant sheet, only keep rows for this tenant.
                if row_tenant and tenant and row_tenant != tenant:
                    continue

                cat = (cat or "").strip()
                subcat = (subcat or "").strip()
                name = (name or "").strip()
                price_str = (price_str or "").strip()
                stock = (stock or "").strip()

                if not cat or not name or not price_str:
                    # enforce the same validity as sheetDoctor()
                    continue

                by_cat.setdefault(cat, []).append(
                    {
                        "name": name,
                        "price_str": price_str,
                        "subcategory": subcat,
                        "stock": stock,
                    }
                )

            if not by_cat:
                return None

            product_catalog: List[Dict[str, Any]] = []
            for cname, items in by_cat.items():
                product_catalog.append(
                    {
                        "name": cname,
                        "items": items,
                    }
                )

            return {"product_catalog": product_catalog}

        except Exception:
            return None
