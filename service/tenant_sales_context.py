"""Bounded, tenant-owned context for V7 sales conversations."""

from __future__ import annotations

import re
from typing import Any, Dict, List


def _text(value: Any, maximum: int) -> str:
    cleaned = " ".join(str(value or "").split())
    return cleaned[:maximum].strip()


def _string_list(value: Any, *, limit: int, item_maximum: int) -> List[str]:
    if not isinstance(value, list):
        return []
    values: List[str] = []
    for raw in value:
        item = _text(raw, item_maximum)
        if item and item not in values:
            values.append(item)
        if len(values) == limit:
            break
    return values


def build_tenant_sales_context(
    business_profile: Any,
    sales_playbook: Any,
    categories: Any,
) -> Dict[str, Any]:
    """Return small, JSON-safe business facts suitable for planning and UI flow."""
    profile = business_profile if isinstance(business_profile, dict) else {}
    playbook = sales_playbook if isinstance(sales_playbook, dict) else {}
    category_rows = categories if isinstance(categories, list) else []

    category_names: List[str] = []
    for category in category_rows:
        if not isinstance(category, dict):
            continue
        name = _text(category.get("name") or category.get("id"), 80)
        if name and name not in category_names:
            category_names.append(name)
        if len(category_names) == 8:
            break

    return {
        "name": _text(profile.get("name"), 120),
        "about": _text(profile.get("about"), 600),
        "business_focus": _text(playbook.get("business_focus"), 240),
        "ideal_customer": _text(playbook.get("ideal_customer"), 240),
        "value_propositions": _string_list(
            playbook.get("value_propositions"), limit=5, item_maximum=160
        ),
        "offering_type": _text(playbook.get("offering_type"), 24),
        "primary_goal": _text(playbook.get("primary_goal"), 40),
        "business_model": _text(playbook.get("business_model") or "general", 40),
        "fulfilment_mode": _text(playbook.get("fulfilment_mode") or "auto", 24),
        "customer_type": _text(playbook.get("customer_type") or "both", 24),
        "response_guidance": _text(playbook.get("response_guidance"), 600),
        "categories": category_names,
    }


def planning_business_context(context: Any, message: str) -> Dict[str, Any]:
    """Allowlist and bound public facts/preferences before an external planner call."""
    source = context if isinstance(context, dict) else {}
    result = {
        "name": _text(source.get("name"), 120),
        "about": _text(source.get("about"), 600),
        "focus": _text(source.get("business_focus"), 240),
        "ideal_customer": _text(source.get("ideal_customer"), 240),
        "offering_type": _text(source.get("offering_type"), 24),
        "primary_goal": _text(source.get("primary_goal"), 40),
        "business_model": _text(source.get("business_model"), 40),
        "fulfilment_mode": _text(source.get("fulfilment_mode"), 24),
        "customer_type": _text(source.get("customer_type"), 24),
        "response_guidance": _text(source.get("response_guidance"), 600),
        "categories": _string_list(source.get("categories"), limit=8, item_maximum=80),
    }
    core = source.get("business_core")
    if not isinstance(core, dict):
        return result

    # Prefer records related to the question rather than always sending the first
    # records. No work, accounts, analytics or arbitrary nested fields are copied.
    words = set(re.findall(r"\w+", message.casefold())) - {
        "the", "a", "an", "and", "for", "to", "of", "i", "you", "is", "do", "can",
    }
    public: Dict[str, Any] = {"industry": _text(core.get("industry"), 200)}
    for collection, fields, limit in (
        ("offerings", {"name": 200, "category": 80, "type": 24, "price_type": 24, "description": 240}, 8),
        ("locations", {"name": 200, "type": 32, "service_area": 200}, 5),
        ("business_rules", {"title": 200, "description": 360}, 5),
    ):
        rows = core.get(collection)
        if not isinstance(rows, list):
            continue
        candidates = []
        for row in rows[:1000]:
            if not isinstance(row, dict) or row.get("active") is not True:
                continue
            record = {key: _text(row.get(key), maximum) for key, maximum in fields.items()
                      if isinstance(row.get(key), str)}
            if collection == "business_rules":
                record["requires_manual_review"] = row.get("requires_manual_review") is True
            score = len(words & set(re.findall(r"\w+", " ".join(
                value for value in record.values() if isinstance(value, str)
            ).casefold())))
            candidates.append((score, record))
        candidates.sort(key=lambda candidate: candidate[0], reverse=True)
        public[collection] = [record for _, record in candidates[:limit]]
    result["business_core"] = public
    return result


def conversation_scope(context: Dict[str, Any], plural: str) -> str:
    """Choose the most useful configured description without inventing claims."""
    focus = _text(context.get("business_focus"), 240)
    if focus:
        return focus
    about = _text(context.get("about"), 320)
    if about:
        return about
    categories = _string_list(context.get("categories"), limit=3, item_maximum=80)
    if categories:
        return f"{', '.join(categories)} and other {plural}"
    return plural


def discovery_question(context: Dict[str, Any], singular: str, plural: str) -> str:
    """Ask one grounded question that moves an unstructured enquiry forward."""
    categories = _string_list(context.get("categories"), limit=3, item_maximum=80)
    if categories:
        choices = ", ".join(categories)
        return f"What are you looking for - {choices}, or something else?"

    ideal_customer = _text(context.get("ideal_customer"), 160)
    if ideal_customer:
        return f"What would you like help achieving with this {singular}?"
    return f"What {singular} or outcome are you looking for today?"


def catalogue_suggestions(context: Dict[str, Any], fallback: List[str]) -> List[str]:
    """Offer real tenant categories before generic navigation suggestions."""
    categories = _string_list(context.get("categories"), limit=3, item_maximum=80)
    return categories or list(fallback)
