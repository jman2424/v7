"""Bounded, tenant-owned context for V7 sales conversations."""

from __future__ import annotations

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
        "categories": category_names,
    }


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
