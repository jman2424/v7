# ai_modes/v7_tool_runtime.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _unwrap_tool_result(res: Any) -> Any:
    """
    Tools sometimes return wrappers like:
      - {"result": {...}}
      - {"ok": True, "data": {...}}
      - {"ok": True, "nearest": {...}}
    We unwrap common wrappers safely.
    """
    if isinstance(res, dict):
        for k in ("result", "data", "nearest", "branch"):
            v = res.get(k)
            if isinstance(v, dict):
                return v
    return res


def _looks_like_branch(b: Any) -> bool:
    if not isinstance(b, dict):
        return False
    return bool(b.get("id") or b.get("name") or b.get("address") or b.get("postcode") or b.get("phone"))


def apply_tool_result_to_facts(
    *,
    tool_name: str,
    tool_args: Dict[str, Any],
    raw_result: Any,
    facts: Dict[str, Any],
) -> None:
    """
    Canonicalize tool outputs into facts in ONE shape that the renderer expects.
    """

    # ---------------- DELIVERY ----------------
    if tool_name == "policy.delivery_rule_for":
        pc = tool_args.get("postcode")
        rule = raw_result  # usually dict|None

        prev = facts.get("delivery") if isinstance(facts.get("delivery"), dict) else {}
        facts["delivery"] = {
            "postcode": pc,
            "rule": rule,
            "summary": (prev.get("summary") or "").strip(),
        }
        return

    if tool_name == "policy.delivery_summary":
        pc = tool_args.get("postcode")
        summary = (str(raw_result).strip() if raw_result else "")

        prev = facts.get("delivery") if isinstance(facts.get("delivery"), dict) else {}
        facts["delivery"] = {
            "postcode": pc or prev.get("postcode"),
            "rule": prev.get("rule"),
            "summary": summary,
        }
        return

    # ---------------- GEO / NEAREST BRANCH ----------------
    if tool_name == "geo.nearest_for_postcode":
        nearest = _unwrap_tool_result(raw_result)

        if _looks_like_branch(nearest):
            facts.setdefault("branch", {})
            facts["branch"]["nearest"] = nearest   # <-- REQUIRED SHAPE
        return

    # ---------------- CATALOG ----------------
    if tool_name == "catalog.search":
        facts["items"] = raw_result if isinstance(raw_result, list) else []
        return

    if tool_name == "catalog.price_of":
        facts.setdefault("price", {})
        if isinstance(raw_result, dict):
            facts["price"].update(raw_result)
        else:
            facts["price"]["price"] = raw_result
        return

    if tool_name == "catalog.in_stock":
        facts.setdefault("price", {})
        facts["price"]["in_stock"] = bool(raw_result) if raw_result is not None else None
        return

    # ---------------- FAQ ----------------
    if tool_name == "faq.best_match":
        if isinstance(raw_result, dict):
            facts["faq"] = raw_result
        return

    # ---------------- FALLBACK ----------------
    # Keep raw result somewhere for debugging (optional)
    facts.setdefault("_raw_tools", {})
    facts["_raw_tools"][tool_name] = raw_result


@dataclass
class ToolRuntime:
    """
    Executes ToolCalls and builds grounded facts in a consistent shape.
    Expects your deps object to expose tool callables using dotted names, e.g:
      policy.delivery_rule_for
      geo.nearest_for_postcode
      catalog.search
    """
    deps: Dict[str, Any]

    def _resolve(self, dotted: str):
        parts = dotted.split(".")
        if len(parts) != 2:
            raise ValueError(f"Tool name must be like 'geo.nearest_for_postcode', got: {dotted}")
        obj = self.deps.get(parts[0])
        if obj is None:
            raise KeyError(f"Missing dep for tool namespace: {parts[0]}")
        fn = getattr(obj, parts[1], None)
        if not callable(fn):
            raise AttributeError(f"Tool not callable: {dotted}")
        return fn

    def run_tools(self, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        facts: Dict[str, Any] = {}

        for tc in tools:
            name = tc.get("name")
            args = tc.get("args") or {}
            required = bool(tc.get("required", False))

            try:
                fn = self._resolve(name)
                res = fn(**args)
                apply_tool_result_to_facts(tool_name=name, tool_args=args, raw_result=res, facts=facts)
            except Exception as e:
                facts.setdefault("_errors", [])
                facts["_errors"].append({"tool": name, "error": repr(e), "args": args})
                if required:
                    # required tool failed → stop early
                    break

        return facts
