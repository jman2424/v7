"""Tenant-scoped offers that can be shown without model inference."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional


_OFFER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class OfferStore:
    """Loads configured offers and returns only currently active entries."""

    def __init__(self, storage: Any) -> None:
        self.storage = storage
        self._offers = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        try:
            data = self.storage.read_json(self.storage.tenant_key, "offers.json")
        except (FileNotFoundError, ValueError):
            return []
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    @classmethod
    def validate(cls, offers: Any) -> None:
        """Validate constraints that are clearer here than in JSON Schema."""
        if not isinstance(offers, list):
            raise ValueError("offers_must_be_array")

        if len(offers) > 500 or sum(item.get("archived") is not True for item in offers if isinstance(item, dict)) > 50:
            raise ValueError("Maximum 50 current offers and 500 total offers including history.")
        ids = set()
        for offer in offers:
            if not isinstance(offer, dict):
                raise ValueError("invalid_offer")
            offer_id = str(offer.get("id") or "").strip()
            if not _OFFER_ID.fullmatch(offer_id):
                raise ValueError("invalid_offer_id")
            if offer_id in ids:
                raise ValueError("duplicate_offer_id")
            ids.add(offer_id)

            deal = offer.get("deal_type", "custom")
            if not isinstance(deal, str) or deal not in {"custom", "buy_one_get_one", "minimum_spend"}:
                raise ValueError("invalid_offer_deal_type")
            if deal == "buy_one_get_one" and not offer.get("product_skus"):
                raise ValueError("Choose eligible catalogue references for the buy-one-get-one deal.")
            if deal == "minimum_spend":
                try:
                    minimum = Decimal(str(offer.get("minimum_spend")))
                    discount = Decimal(str(offer.get("discount_value")))
                    discount_type = offer.get("discount_type")
                    if not minimum.is_finite() or not discount.is_finite() or not 0 < minimum <= 1000000 or not 0 < discount <= 1000000:
                        raise ValueError
                    if minimum.as_tuple().exponent < -2 or discount.as_tuple().exponent < -2:
                        raise ValueError
                    if not isinstance(discount_type, str) or discount_type not in {"percentage", "fixed"} or discount > (100 if discount_type == "percentage" else minimum):
                        raise ValueError
                except (InvalidOperation, ValueError):
                    raise ValueError("Enter a positive minimum spend and valid discount, with at most two decimal places.") from None
            starts_on = cls._parse_date(offer.get("starts_on"), "invalid_offer_start_date")
            ends_on = cls._parse_date(offer.get("ends_on"), "invalid_offer_end_date")
            if starts_on and ends_on and starts_on > ends_on:
                raise ValueError("offer_end_before_start")

            product_skus = offer.get("product_skus") or []
            if not isinstance(product_skus, list) or not all(isinstance(sku, str) for sku in product_skus):
                raise ValueError("invalid_offer_product_skus")
            if len(product_skus) != len({str(sku).strip() for sku in product_skus}):
                raise ValueError("duplicate_offer_product_sku")

    @staticmethod
    def _parse_date(value: Any, error: str) -> Optional[date]:
        if value in (None, ""):
            return None
        try:
            return date.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError(error) from exc

    def active(self, *, today: Optional[date] = None) -> List[Dict[str, Any]]:
        current_day = today or datetime.now(timezone.utc).date()
        active: List[Dict[str, Any]] = []
        for offer in self._offers:
            if offer.get("active") is not True or offer.get("archived") is True:
                continue
            try:
                self.validate([offer])
                starts_on = self._parse_date(offer.get("starts_on"), "invalid_offer_start_date")
                ends_on = self._parse_date(offer.get("ends_on"), "invalid_offer_end_date")
            except ValueError:
                continue
            if starts_on and starts_on > current_day:
                continue
            if ends_on and ends_on < current_day:
                continue
            active.append(dict(offer))
        return active
