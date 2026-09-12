"""Sales-agent conversation policy for grounded V7 replies.

The retrieval and reasoning layers establish facts. This module only decides
which customer step is most useful next, so it never invents products, prices,
delivery coverage, or commitments on a business's behalf.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from service.sales_playbook import load_sales_playbook, offering_terms
from service.tenant_sales_context import build_tenant_sales_context, catalogue_suggestions


_GENERIC_CTA = re.compile(
    r"\s+(?:anything else you(?:'|\u2019)d like to check\?|want to look at anything else\?|"
    r"anything else i can help you with\?)$",
    re.IGNORECASE,
)


class SalesAgentPolicy:
    """Turn a grounded answer into the next useful sales conversation step."""

    def __init__(
        self,
        *,
        overrides: Any = None,
        catalog: Any = None,
        business_profile: Any = None,
    ) -> None:
        self.overrides = overrides
        self.catalog = catalog
        self.business_profile = business_profile if isinstance(business_profile, dict) else {}

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
        if (
            prompt
            and prompt.casefold() not in text.casefold()
            and "?" not in text
            and not self._already_requests_next_action(text, agent["next_action"])
        ):
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
        playbook = load_sales_playbook(self.overrides)
        singular, plural = offering_terms(playbook)
        intent = str(response.get("intent") or "unknown").strip().lower()
        facts = response.get("facts") if isinstance(response.get("facts"), dict) else {}
        entities = response.get("entities") if isinstance(response.get("entities"), dict) else {}
        items = facts.get("items") if isinstance(facts.get("items"), list) else []
        delivery = facts.get("delivery") if isinstance(facts.get("delivery"), dict) else {}
        offers = facts.get("offers") if isinstance(facts.get("offers"), dict) else {}
        offer_items = offers.get("items") if isinstance(offers.get("items"), list) else []
        previous = session.get("sales_agent") if isinstance(session.get("sales_agent"), dict) else {}

        state = self._default_state(playbook, singular, plural)

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
                objective="Collect the contact details the customer chooses to share.",
                next_action="collect_contact_details",
                next_question="",
                suggested_replies=[],
            )
        elif intent == "handoff_contact_captured":
            state.update(
                stage="handoff",
                objective="Keep the customer's contact details with the tenant's lead record.",
                next_action="team_follow_up",
                next_question="",
                suggested_replies=[],
            )
        elif intent == "compare_products":
            suggestions = self._item_names(items)
            if len(items) == 2:
                state.update(
                    stage="recommend",
                    objective="Help the customer choose between grounded product options.",
                    next_action="select_compared_product",
                    next_question="Which option would you like to take forward?",
                    suggested_replies=suggestions,
                )
            else:
                state.update(
                    stage="discover",
                    objective="Identify the two products the customer wants to compare.",
                    next_action="collect_comparison_products",
                    next_question="",
                    suggested_replies=[],
                )
        elif intent == "unavailable_product":
            suggestions = self._item_names(items)
            if suggestions:
                state.update(
                    stage="recommend",
                    objective="Guide the customer to an available, tenant-catalog alternative.",
                    next_action="select_available_alternative",
                    next_question="Which available alternative would you like to look at?",
                    suggested_replies=suggestions,
                )
            else:
                state.update(
                    stage="assist",
                    objective="Give an accurate stock update without inventing an alternative.",
                    next_action="browse_other_products",
                    next_question="",
                    suggested_replies=["Browse products", "Check delivery"],
                )
        elif intent == "offers":
            if offer_items:
                state.update(
                    stage="convert",
                    objective="Help the customer use a current, tenant-configured offer.",
                    next_action="offer_product_guidance",
                    next_question="Tell me which product you are interested in and I will check the current offer details.",
                    suggested_replies=["Browse products", "Check delivery"],
                )
            else:
                state.update(
                    stage="assist",
                    objective="Give an accurate update when no active offer is configured.",
                    next_action="await_customer_question",
                    next_question="",
                    suggested_replies=["Browse products", "Check delivery"],
                )
        elif delivery:
            if delivery.get("rule"):
                if session.get("last_sku"):
                    state.update(
                        stage="convert",
                        objective="Move from a selected product and delivery eligibility to an owner handoff.",
                        next_action="arrange_order_handoff",
                        next_question="Would you like the team to help arrange this for delivery?",
                        suggested_replies=["Speak to someone", "Browse more products"],
                    )
                else:
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
        elif intent == "price_check":
            state.update(
                stage="convert",
                objective="Help the customer complete a suitable order.",
                next_action="confirm_fulfilment",
                next_question="Would you like to check delivery or compare another option?",
                suggested_replies=["Check delivery"],
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
        elif intent in {"faq", "store_info"}:
            state.update(
                stage="assist",
                objective="Answer a grounded business question without interrupting the customer.",
                next_action="await_customer_question",
                next_question="",
                suggested_replies=["Browse products", "Check delivery", "Nearest branch"],
            )
        elif intent in {"system_no_results", "system_force_browse", "system_clarify"}:
            state.update(
                stage="discover",
                objective="Narrow the request to something the business can fulfil.",
                next_action="refine_need",
                next_question="",
                suggested_replies=["Check delivery", "Nearest branch"],
            )

        self._adapt_state_for_playbook(
            state,
            intent=intent,
            playbook=playbook,
            singular=singular,
            plural=plural,
        )
        self._apply_qualification_question(
            state,
            intent=intent,
            user_text=user_text,
            previous=previous,
            playbook=playbook,
            singular=singular,
            plural=plural,
            has_items=bool(items or offer_items),
        )

        if previous.get("stage") and previous.get("stage") != state["stage"]:
            state["previous_stage"] = previous["stage"]
        if entities.get("postcode"):
            state["postcode_confirmed"] = True
        return state

    def _default_state(self, playbook: Dict[str, Any], singular: str, plural: str) -> Dict[str, Any]:
        goal = playbook["primary_goal"]
        if goal == "book_consultation":
            return {
                "stage": "discover",
                "objective": "Understand what the customer wants to discuss with the team.",
                "next_action": "discover_consultation_need",
                "next_question": "What would you like to discuss with the team?",
                "suggested_replies": ["Book a consultation", "Ask a question"],
            }
        if goal == "capture_leads":
            return {
                "stage": "discover",
                "objective": "Understand the customer's need before offering a team follow-up.",
                "next_action": "discover_need",
                "next_question": "What can the team help you with today?",
                "suggested_replies": ["Speak to someone", "Ask a question"],
            }
        if goal == "answer_questions":
            return {
                "stage": "discover",
                "objective": "Understand the business question the customer wants answered.",
                "next_action": "discover_question",
                "next_question": "What would you like to know?",
                "suggested_replies": [f"Browse {plural}", "Ask a question"],
            }
        if singular != "product":
            return {
                "stage": "discover",
                "objective": f"Understand which {singular} or outcome the customer needs.",
                "next_action": "discover_need",
                "next_question": f"What {singular} or outcome are you looking for today?",
                "suggested_replies": [f"Browse {plural}", "Speak to someone"],
            }
        return {
                "stage": "discover",
                "objective": "Understand what the customer wants to buy or arrange.",
                "next_action": "discover_need",
                "next_question": "What are you shopping for today?",
                "suggested_replies": self._browse_suggestions(["Check delivery", "Nearest branch"]),
            }

    def _browse_suggestions(self, fallback: List[str]) -> List[str]:
        categories: List[Dict[str, Any]] = []
        if self.catalog:
            try:
                categories = [item for item in self.catalog.categories() if isinstance(item, dict)]
            except Exception:
                categories = []
        context = build_tenant_sales_context(
            self.business_profile,
            load_sales_playbook(self.overrides),
            categories,
        )
        return catalogue_suggestions(context, fallback)

    def _adapt_state_for_playbook(
        self,
        state: Dict[str, Any],
        *,
        intent: str,
        playbook: Dict[str, Any],
        singular: str,
        plural: str,
    ) -> None:
        if singular != "product":
            state["objective"] = self._replace_customer_terms(str(state["objective"]), singular, plural)
            state["next_question"] = self._replace_customer_terms(str(state["next_question"]), singular, plural)
            state["suggested_replies"] = [
                self._replace_customer_terms(str(reply), singular, plural)
                for reply in state["suggested_replies"]
            ]

        if intent != "price_check":
            return

        goal = playbook["primary_goal"]
        if goal == "book_consultation":
            state.update(
                objective="Move from a selected option to a consultation with the team.",
                next_action="book_consultation",
                next_question="Would you like the team to arrange a consultation?",
                suggested_replies=["Book a consultation", "Ask another question"],
            )
        elif goal == "capture_leads":
            state.update(
                objective="Offer a follow-up after the customer has explored an option.",
                next_action="request_follow_up",
                next_question="Would you like the team to follow up?",
                suggested_replies=["Speak to someone", "Ask another question"],
            )
        elif goal == "answer_questions":
            state.update(
                stage="assist",
                objective="Keep helping with grounded business questions.",
                next_action="await_customer_question",
                next_question="",
                suggested_replies=[f"Browse {plural}", "Ask a question"],
            )
        elif singular != "product":
            state.update(
                objective=f"Help the customer take the next step for this {singular}.",
                next_action="arrange_team_handoff",
                next_question="Would you like the team to help you get started?",
                suggested_replies=["Speak to someone", f"Browse more {plural}"],
            )

    @staticmethod
    def _replace_customer_terms(text: str, singular: str, plural: str) -> str:
        replaced = re.sub(r"\bproducts\b", plural, text, flags=re.IGNORECASE)
        replaced = re.sub(r"\bproduct\b", singular, replaced, flags=re.IGNORECASE)
        replaced = re.sub(r"\borders?\b", "next step", replaced, flags=re.IGNORECASE)
        replaced = re.sub(r"\bstock\b", "availability", replaced, flags=re.IGNORECASE)
        return replaced

    def _apply_qualification_question(
        self,
        state: Dict[str, Any],
        *,
        intent: str,
        user_text: str,
        previous: Dict[str, Any],
        playbook: Dict[str, Any],
        singular: str,
        plural: str,
        has_items: bool,
    ) -> None:
        questions = playbook["qualification_questions"]
        if previous.get("qualification_complete"):
            state["qualification_complete"] = True
            return
        if not questions or intent in {"human_handoff", "handoff", "handoff_contact_captured", "out_of_scope", "system_error"}:
            return

        previous_action = str(previous.get("next_action") or "")
        continuing = previous_action == "ask_qualification_question" or bool(previous.get("qualification_pending"))
        starting = has_items or intent == "price_check"
        if not continuing and not starting:
            return

        # A customer's own question is not an answer to our qualification question.
        # Answer it first and retain the pending step for the next substantive reply.
        acknowledgement = bool(re.fullmatch(r"(?:thanks|thank you|cheers|ok(?:ay)?|no thanks|not now)[.! ]*", user_text.strip(), re.I))
        question = "?" in user_text or bool(re.match(r"^(?:what|when|where|why|how|who|can|could|do|does|is|are|will|would)\b", user_text.strip(), re.I))
        if continuing and (acknowledgement or question or intent in {"faq", "store_info", "check_delivery", "ask_postcode", "check_delivery_needs_postcode", "smalltalk", "greeting"}):
            state.update(qualification_index=self._qualification_index(previous), qualification_pending=True)
            state["next_question"] = ""
            return

        if continuing and (not user_text.strip() or intent in {"system_empty", "system_clarify"}):
            index = self._qualification_index(previous)
        elif continuing:
            index = self._qualification_index(previous) + 1
        else:
            index = 0

        if index < len(questions):
            state.update(
                stage="qualify",
                objective=f"Learn the detail needed to guide the customer to the right {singular}.",
                next_action="ask_qualification_question",
                next_question=questions[index],
                suggested_replies=[],
                qualification_index=index,
                qualification_pending=True,
            )
            return

        if continuing:
            self._complete_qualification(state, playbook, singular, plural)
            state["qualification_complete"] = True

    @staticmethod
    def _qualification_index(previous: Dict[str, Any]) -> int:
        try:
            return max(int(previous.get("qualification_index") or 0), 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _complete_qualification(
        state: Dict[str, Any],
        playbook: Dict[str, Any],
        singular: str,
        plural: str,
    ) -> None:
        goal = playbook["primary_goal"]
        if goal == "book_consultation":
            state.update(
                stage="convert",
                objective="Move a qualified customer to a consultation with the team.",
                next_action="book_consultation",
                next_question="Would you like the team to arrange a consultation?",
                suggested_replies=["Book a consultation", "Ask another question"],
            )
        elif goal == "capture_leads":
            state.update(
                stage="convert",
                objective="Offer a follow-up after the customer's need is qualified.",
                next_action="request_follow_up",
                next_question="Would you like the team to follow up?",
                suggested_replies=["Speak to someone", "Ask another question"],
            )
        elif goal == "answer_questions":
            state.update(
                stage="assist",
                objective="Continue answering grounded business questions.",
                next_action="await_customer_question",
                next_question="",
                suggested_replies=[f"Browse {plural}", "Ask a question"],
            )
        elif singular != "product":
            state.update(
                stage="convert",
                objective=f"Help the customer take the next step for this {singular}.",
                next_action="arrange_team_handoff",
                next_question="Would you like the team to help you get started?",
                suggested_replies=["Speak to someone", f"Browse more {plural}"],
            )

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

    @staticmethod
    def _already_requests_next_action(text: str, next_action: str) -> bool:
        if next_action != "compare_or_price_selection":
            return False
        return bool(re.search(r"\btell me (?:the )?(?:number|option)\b", text, re.IGNORECASE))
