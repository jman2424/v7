"""Sales-agent conversation policy for grounded V7 replies.

The retrieval and reasoning layers establish facts. This module only decides
which customer step is most useful next, so it never invents products, prices,
delivery coverage, or commitments on a business's behalf.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


_GENERIC_CTA = re.compile(
    r"\s+(?:anything else you(?:'|\u2019)d like to check\?|want to look at anything else\?|"
    r"anything else i can help you with\?)$",
    re.IGNORECASE,
)


class SalesAgentPolicy:
    """Turn a grounded answer into the next useful sales conversation step."""

    def guide(
        self,
        response: Dict[str, Any],
        *,
        user_text: str,
        session: Dict[str, Any],
    ) -> Dict[str, Any]:
        result = dict(response or {})
        agent = self._next_step(result, user_text=user_text, session=session)

        result["agent"] = agent
        ui = dict(result.get("ui") or {})
        ui["suggested_replies"] = list(agent["suggested_replies"])
        result["ui"] = ui

        prompt = agent["next_question"]
        text = self._remove_generic_cta(str(result.get("reply") or ""))
        if prompt and prompt.casefold() not in text.casefold() and not text.rstrip().endswith("?"):
            text = f"{text.rstrip()} {prompt}".strip()
        result["reply"] = text
        return result

    def _next_step(
        self,
        response: Dict[str, Any],
        *,
        user_text: str,
        session: Dict[str, Any],
    ) -> Dict[str, Any]:
        del user_text
        intent = str(response.get("intent") or "unknown").strip().lower()
        facts = response.get("facts") if isinstance(response.get("facts"), dict) else {}
        entities = response.get("entities") if isinstance(response.get("entities"), dict) else {}
        items = facts.get("items") if isinstance(facts.get("items"), list) else []
        delivery = facts.get("delivery") if isinstance(facts.get("delivery"), dict) else {}
        previous = session.get("sales_agent") if isinstance(session.get("sales_agent"), dict) else {}

        state: Dict[str, Any] = {
            "stage": "discover",
            "objective": "Understand what the customer wants to buy or arrange.",
            "next_action": "discover_need",
            "next_question": "What are you shopping for today?",
            "suggested_replies": ["Check delivery", "Nearest branch"],
        }

        if intent in {"system_error", "out_of_scope"}:
            state.update(
                stage="recover",
                objective="Bring the conversation back to supported business help.",
                next_action="offer_supported_help",
                next_question="",
                suggested_replies=["Check delivery", "Nearest branch"],
            )
        elif intent in {"check_delivery_needs_postcode", "ask_postcode"}:
            state.update(
                stage="qualify",
                objective="Confirm whether the customer can receive their order.",
                next_action="collect_postcode",
                next_question="",
                suggested_replies=[],
            )
        elif intent in {"human_handoff", "handoff"}:
            state.update(
                stage="handoff",
                objective="Collect enough detail for a business follow-up.",
                next_action="collect_contact_preference",
                next_question="What is the best way for the team to contact you?",
                suggested_replies=[],
            )
        elif delivery:
            if delivery.get("rule"):
                state.update(
                    stage="convert",
                    objective="Move from delivery eligibility to a suitable order.",
                    next_action="recommend_products",
                    next_question="What would you like help choosing for your order?",
                    suggested_replies=["Nearest branch"],
                )
            else:
                state.update(
                    stage="qualify",
                    objective="Offer the best available fulfilment path.",
                    next_action="offer_branch_option",
                    next_question="Would you like me to help find the nearest branch instead?",
                    suggested_replies=["Nearest branch"],
                )
        elif items:
            suggestions = self._item_names(items)
            state.update(
                stage="recommend",
                objective="Help the customer choose a grounded product option.",
                next_action="compare_or_price_selection",
                next_question="Which option would you like me to compare or price up?",
                suggested_replies=suggestions or ["Show more options", "Check delivery"],
            )
        elif intent == "price_check":
            state.update(
                stage="convert",
                objective="Help the customer complete a suitable order.",
                next_action="confirm_fulfilment",
                next_question="Would you like to check delivery or compare another option?",
                suggested_replies=["Check delivery"],
            )
        elif intent in {"system_no_results", "system_force_browse", "system_clarify"}:
            state.update(
                stage="discover",
                objective="Narrow the request to something the business can fulfil.",
                next_action="refine_need",
                next_question="",
                suggested_replies=["Check delivery", "Nearest branch"],
            )

        if previous.get("stage") and previous.get("stage") != state["stage"]:
            state["previous_stage"] = previous["stage"]
        if entities.get("postcode"):
            state["postcode_confirmed"] = True
        return state

    @staticmethod
    def _item_names(items: List[Any]) -> List[str]:
        names: List[str] = []
        for item in items[:3]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("title") or "").strip()
            if name and name not in names:
                names.append(name)
        return names

    @staticmethod
    def _remove_generic_cta(text: str) -> str:
        return _GENERIC_CTA.sub("", (text or "").strip()).strip()
