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

_QUALIFICATION_FLAGS = (
    "qualification_index", "qualification_pending", "qualification_complete",
    "qualification_declined", "qualification_paused", "qualification_answers",
)
_UNKNOWN_ANSWER = re.compile(
    r"\b(?:i (?:still )?(?:don['’]?t know|do not know|have no idea)|no idea|not sure|"
    r"unsure|undecided|(?:haven['’]?t|have not|not) decided|still (?:thinking|deciding)|"
    r"(?:no|not set a?) budget yet|not yet|not applicable)\b|^\s*(?:maybe|n/a)[.! ]*$", re.I,
)
_DECLINED_ANSWER = re.compile(
    r"(?:no thanks|not now|skip(?: (?:this|that))?(?: question)?|stop(?: asking)?|don['’]t ask|"
    r"(?:i['’]d |i would |i )?(?:rather|prefer) not (?:to (?:say|share|answer)|say|share|answer)|"
    r"(?:i )?(?:don['’]t|do not) want to (?:say|share|answer))"
    r"(?: (?:this|that)(?: question)?| (?:my|the) (?:budget|details|information))?"
    r"(?:,? (?:please|thanks|thank you))?[.! ]*", re.I,
)
_SUPPORT_REQUEST = re.compile(r"\b(?:cancel(?:lation)?|refund|complain(?:t)?|dissatisfied)\b", re.I)

_GOAL_STEPS = {
    "request_quote": {
        "objective": "Help the team prepare a quote for the customer's requirement.",
        "next_action": "request_quote",
        "next_question": "Would you like the team to prepare a quote?",
        "suggested_replies": ["Request a quote", "Ask another question"],
    },
    "book_appointment": {
        "objective": "Offer an appointment request for the team to confirm.",
        "next_action": "request_appointment",
        "next_question": "Would you like the team to arrange an appointment?",
        "suggested_replies": ["Arrange an appointment", "Ask another question"],
    },
    "start_subscription": {
        "objective": "Help the customer discuss a suitable subscription with the team.",
        "next_action": "discuss_subscription",
        "next_question": "Would you like the team to help you choose a subscription?",
        "suggested_replies": ["Discuss a subscription", "Ask another question"],
    },
}


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
        supplied = result.get('agent')
        if (result.get('intent') == 'grounded_answer' and isinstance(supplied, dict)
                and supplied.get('_validated_grounded') is True):
            # The accounted answer already chose and validated a grounded next
            # step. Re-running the catalogue policy used to discard that choice
            # and restart a generic qualification interview on every question.
            agent = dict(supplied)
            agent.pop('_validated_grounded', None)
            previous = session.get('sales_agent')
            if isinstance(previous, dict):
                self._retain_qualification_memory(agent, previous)
                if previous.get('stage') in {'discover', 'qualify', 'recommend', 'convert', 'assist', 'handoff', 'recover'}:
                    if previous['stage'] != agent.get('stage'):
                        agent['previous_stage'] = previous['stage']
        else:
            agent = self._next_step(result, user_text=user_text, session=session)

        result["agent"] = agent
        ui = dict(result.get("ui") or {})
        ui["suggested_replies"] = list(agent["suggested_replies"])
        result["ui"] = ui

        prompt = agent["next_question"]
        text = self._remove_generic_cta(str(result.get("reply") or ""))
        if (
            prompt
            and result.get('intent') != 'grounded_answer'
            and prompt.casefold() not in text.casefold()
            and "?" not in text
            and not self._already_requests_next_action(text, agent["next_action"])
        ):
            text = f"{text.rstrip()}\n\n{prompt}".strip()
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
        self._retain_task_memory(state, previous)
        number = re.fullmatch(r'\s*(\d{1,2})\s*[.)]?\s*',user_text or '')
        if intent=='price_check' and number and isinstance(entities.get('sku'),str):
            references = previous.get('last_offering_ids')
            if not isinstance(references,list) or not references:
                legacy = session.get('last_items')
                references = ['product:'+str(sku) for sku in legacy[:12]] if isinstance(legacy,list) else []
            index = int(number.group(1))-1
            chosen = 'product:'+entities['sku']
            if 0<=index<len(references) and references[index]==chosen:
                # This is a verified displayed choice, not a purchase or a
                # qualification answer. Retain it for the next conversation turn.
                state['selected_offering_id'] = chosen
                # A choice is not an answer to a qualification question. Finish
                # the requested selection without restarting the interview;
                # the next contextual turn can use already supplied details.
                if playbook['qualification_questions']:
                    state.update(stage='assist',next_action='await_customer_question',next_question='',
                                 suggested_replies=[],qualification_paused=True,qualification_pending=False)
                    return state
        abandoned = self._clear_abandoned_choices(state, user_text)
        # Qualification must use reconciled evidence/flags, not the stale
        # completion marker from before a requirement was retired.
        previous = {**previous, **{key: state[key] for key in _QUALIFICATION_FLAGS if key in state}}

        if intent in {"policy", "cancel", "complaint"} or _SUPPORT_REQUEST.search(user_text):
            # Retain the task for a later return to shopping, without showing
            # a sales shortlist, old purchase links or qualification question.
            state.update(stage="assist", objective="Help with the customer's support request.",
                         next_action="await_customer_question", next_question="", suggested_replies=[],
                         offering_ids=[], navigation_ids=[])
            return state

        if intent in {'grounded_answer', 'conversation'}:
            # Older provider responses have no structured state. Their answer
            # still must not receive an unrelated purchase/booking question.
            state.update(stage='assist', objective='Answer the customer\'s current business question.',
                         next_action='await_customer_question', next_question='', suggested_replies=[])
            if previous.get('qualification_complete'):
                state['qualification_complete'] = True
            return state
        if intent in {"system_error", "out_of_scope"}:
            state.update(
                stage="recover",
                objective="Bring the conversation back to supported business help.",
                next_action="offer_supported_help",
                next_question="",
                suggested_replies=[],
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
        elif intent == "business_knowledge" and not items:
            state.update(
                stage="assist",
                objective="Answer the business question using configured public facts.",
                next_action="await_customer_question",
                next_question="",
                suggested_replies=[f"Browse {plural}", "Ask a question"],
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
            items=items,
        )
        if abandoned:
            state.update(stage="assist", next_action="await_customer_question", next_question="",
                         suggested_replies=[])
            return state
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

    def _retain_task_memory(self, state: Dict[str, Any], previous: Dict[str, Any]) -> None:
        """Carry only already validated task facts, never the old sales action.

        This runs only for deterministic/legacy replies. A newly validated
        grounded state, including an explicit clear or correction, bypasses it.
        """
        for key in ("offering_ids", "last_offering_ids", "navigation_ids"):
            rows = previous.get(key)
            if isinstance(rows, list):
                state[key] = list(dict.fromkeys(row for row in rows[:3]
                    if isinstance(row, str) and 0 < len(row) <= 128
                    and (key == "navigation_ids" or row.startswith(("product:", "offering:")))))
        if state.get("offering_ids") and not state.get("last_offering_ids"):
            state["last_offering_ids"] = list(state["offering_ids"])
        selected = previous.get("selected_offering_id")
        if selected is None or (isinstance(selected, str)
                and selected.startswith(("product:", "offering:")) and len(selected) <= 128):
            if "selected_offering_id" in previous:
                state["selected_offering_id"] = selected
        retired = previous.get("retired_requirements")
        if isinstance(retired, list):
            state["retired_requirements"] = [row for row in retired[-6:]
                if isinstance(row, str) and 0 < len(row) <= 180]
        requirements = previous.get("requirements")
        if isinstance(requirements, list):
            state["requirements"] = [row for row in requirements[:6]
                if isinstance(row, str) and 0 < len(row) <= 180
                and row not in state.get("retired_requirements", [])]
        self._retain_qualification_memory(state, previous)

    def _retain_qualification_memory(self, state: Dict[str, Any], previous: Dict[str, Any]) -> None:
        if state.pop('_reset_qualification', False) is True:
            state.update(qualification_answers={}, qualification_complete=False, qualification_index=0,
                         qualification_pending=False, qualification_paused=True,
                         qualification_declined=previous.get('qualification_declined') is True)
            return
        for key in _QUALIFICATION_FLAGS:
            value = previous.get(key)
            if key == "qualification_index":
                if type(value) is int and 0 <= value <= 4:
                    state[key] = value
            elif key != "qualification_answers" and type(value) is bool:
                state[key] = value
        questions = load_sales_playbook(self.overrides)["qualification_questions"]
        current = {**previous, "retired_requirements": state.get("retired_requirements",
                                                                previous.get("retired_requirements", []))}
        answers = self._qualification_answers(current, questions)
        raw = previous.get("qualification_answers")
        added = [row for row in state.get('requirements', [])
                 if row not in previous.get('requirements', [])]
        for question in questions:
            row = answers.get(question)
            if (isinstance(row, dict) and row.get('status') == 'answered'
                    and any(self._known_qualification_detail(question, requirement)
                            and requirement != row['evidence'] for requirement in added)):
                # A deterministic interview may have stored its evidence only
                # in this map. A newly verified budget/timing detail supersedes
                # that answer even when there was no old requirement to retire.
                answers.pop(question)
        if isinstance(raw, dict):
            state["qualification_answers"] = answers
        invalidated = [index for index, question in enumerate(questions)
                       if isinstance(raw, dict) and isinstance(raw.get(question), dict)
                       and raw[question].get("status") == "answered" and question not in answers]
        # Older completed sessions may predate the answer evidence map. A new
        # retirement invalidates that untraceable completion conservatively.
        if (not isinstance(raw, dict) and questions and previous.get("qualification_complete")
                and current["retired_requirements"] != previous.get("retired_requirements", [])):
            invalidated = [0]
        if invalidated:
            declined = bool(state.get("qualification_declined"))
            state.update(qualification_complete=False, qualification_index=min(invalidated),
                         qualification_pending=False, qualification_paused=not declined)

    def _clear_abandoned_choices(self, state: Dict[str, Any], user_text: str) -> bool:
        """Apply clear refusals locally when the provider cannot validate a turn."""
        # Asking about rejecting an option is not itself a choice or refusal.
        if "?" in user_text or re.match(r"^\s*(?:what|when|where|why|how|can|could|do|does|is|are|will|would)\b", user_text, re.I):
            return False
        selected = state.get("selected_offering_id")
        keys = list(dict.fromkeys([key for key in [selected] + state.get("offering_ids", [])
                                  + state.get("last_offering_ids", []) if isinstance(key, str)]))
        rejected = set()
        for key in keys:
            suffix = key.split(":", 1)[-1]
            aliases = [suffix]
            if key.startswith("product:") and self.catalog:
                try:
                    item = self.catalog.get_item_by_sku(suffix)
                    if isinstance(item, dict) and isinstance(item.get("name"), str):
                        aliases.append(item["name"])
                except Exception:
                    pass
            for alias in aliases:
                if alias and re.search(
                    r"\b(?:forget|drop|remove|exclude|(?:i )?(?:do not|don['’]t|no longer) want)\s+"
                    r"(?:the\s+)?(?<!\w)" + re.escape(alias) + r"(?!\w)", user_text, re.I,
                ):
                    rejected.add(key)
        if selected and not _SUPPORT_REQUEST.search(user_text) and re.search(
            r"\b(?:forget (?:that|this|my selected|the selected) (?:option|plan|product|choice)|"
            r"(?:i )?(?:do not|don['’]t|no longer) want "
            r"(?:it|(?:that|this)(?: (?:option|plan|product|choice|subscription))?)"
            r"(?: anymore| any more)?(?=$|[.!;,]))",
            user_text, re.I,
        ):
            rejected.add(selected)
        if not rejected:
            return False
        for field in ("offering_ids", "last_offering_ids"):
            state[field] = [key for key in state.get(field, []) if key not in rejected]
        if selected in rejected:
            state["selected_offering_id"] = None
            state["navigation_ids"] = []
        return True

    def _default_state(self, playbook: Dict[str, Any], singular: str, plural: str) -> Dict[str, Any]:
        goal = playbook["primary_goal"]
        if goal in _GOAL_STEPS:
            questions = {
                "request_quote": "What would you like the team to quote for?",
                "book_appointment": "What would you like an appointment for?",
                "start_subscription": "What do you need from a subscription?",
            }
            return {
                "stage": "discover",
                "objective": _GOAL_STEPS[goal]["objective"],
                "next_action": "discover_need",
                "next_question": questions[goal],
                "suggested_replies": [f"Browse {plural}", "Ask a question"],
            }
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
        items: List[Any],
    ) -> None:
        if singular != "product":
            state["objective"] = self._replace_customer_terms(str(state["objective"]), singular, plural)
            state["next_question"] = self._replace_customer_terms(str(state["next_question"]), singular, plural)
            state["suggested_replies"] = [
                self._replace_customer_terms(str(reply), singular, plural)
                for reply in state["suggested_replies"]
            ]

        mode = playbook.get("fulfilment_mode", "auto")
        supports_delivery = mode == "delivery" or (mode in {"auto", "hybrid"} and singular == "product")
        if not supports_delivery:
            state["suggested_replies"] = [reply for reply in state["suggested_replies"]
                                          if reply.casefold() not in {"check delivery", "nearest branch"}]
            if state["next_action"] == "confirm_fulfilment":
                state.update(
                    objective="Help the customer arrange the appropriate next step with the team.",
                    next_action="arrange_team_handoff",
                    next_question="Would you like the team to help with the next step?",
                    suggested_replies=["Speak to someone", f"Browse more {plural}"],
                )
            elif not state["suggested_replies"] and state["stage"] not in {"handoff", "qualify"}:
                state["suggested_replies"] = [f"Browse {plural}", "Ask a question"]

        if intent != "price_check" and not (intent == "business_knowledge" and len(items) == 1):
            return

        goal = playbook["primary_goal"]
        if goal in _GOAL_STEPS:
            state.update(stage="convert", **_GOAL_STEPS[goal])
        elif goal == "drive_sales" and len(items) == 1 and isinstance(items[0], dict) and items[0].get("price_type") == "quote":
            state.update(stage="convert", **_GOAL_STEPS["request_quote"])
        elif goal == "book_consultation":
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
        answers = self._qualification_answers(previous, questions)
        if answers:
            state["qualification_answers"] = answers
        if not questions or intent in {"human_handoff", "handoff", "handoff_contact_captured", "out_of_scope", "system_error"}:
            return
        if previous.get("qualification_declined"):
            state.update(stage="assist", next_action="await_customer_question", next_question="",
                         suggested_replies=["Ask a question"], qualification_declined=True,
                         qualification_complete=False, qualification_pending=False)
            return
        if previous.get("qualification_complete"):
            state["qualification_complete"] = True
            return
        previous_action = str(previous.get("next_action") or "")
        continuing = previous_action == "ask_qualification_question" or bool(previous.get("qualification_pending"))
        starting = has_items or intent == "price_check"
        current_index = min(self._qualification_index(previous), len(questions) - 1)
        if _DECLINED_ANSWER.fullmatch(user_text.strip()):
            evidence = self._customer_evidence(user_text)
            if continuing and evidence:
                answers[questions[current_index]] = {"status": "declined", "evidence": evidence}
            state.update(stage="assist", next_action="await_customer_question", next_question="",
                         suggested_replies=["Ask a question"], qualification_complete=False,
                         qualification_declined=True, qualification_pending=False,
                         qualification_answers=answers)
            return
        if not continuing and not starting:
            return

        # A customer's own question is not an answer to our qualification question.
        # Answer it first and retain the pending step for the next substantive reply.
        acknowledgement = bool(re.fullmatch(r"(?:thanks|thank you|cheers|ok(?:ay)?|no thanks|not now)[.! ]*", user_text.strip(), re.I))
        question = "?" in user_text or bool(re.match(r"^(?:what|when|where|why|how|who|can|could|do|does|is|are|will|would)\b", user_text.strip(), re.I))
        other_help = bool(re.match(r"^(?:show|browse|compare|check|tell me|find|explain|help me|list)\b",
                                  user_text.strip(), re.I))
        numbered_choice = bool(re.fullmatch(r'\s*(?:option\s*)?\d{1,2}\s*[.)]?\s*', user_text, re.I))
        if continuing and (acknowledgement or question or other_help or numbered_choice or intent in {"faq", "store_info", "check_delivery", "ask_postcode", "check_delivery_needs_postcode", "smalltalk", "greeting"}):
            state.update(qualification_index=self._qualification_index(previous), qualification_pending=True)
            state["next_question"] = ""
            return

        if continuing and (not user_text.strip() or intent in {"system_empty", "system_clarify"}):
            state["next_question"] = ""
            return
        elif continuing:
            evidence = self._customer_evidence(user_text)
            # An unavailable detail is not an answered question. Pause without
            # repeating the interview; a later substantive answer can resume it.
            if not evidence or _UNKNOWN_ANSWER.search(user_text):
                if evidence:
                    answers[questions[current_index]] = {"status": "unknown", "evidence": evidence}
                state.update(stage="assist", next_action="await_customer_question", next_question="",
                             suggested_replies=["Ask a question"], qualification_index=current_index,
                             qualification_pending=True, qualification_paused=True,
                             qualification_complete=False, qualification_answers=answers)
                return
            answers[questions[current_index]] = {"status": "answered", "evidence": evidence}
            index = current_index + 1
        else:
            index = 0

        # Only skip a future question when a verified, non-retired requirement
        # supplies an obvious budget or timing detail. Arbitrary tenant-defined
        # questions remain untouched rather than guessing their business meaning.
        requirements = previous.get("requirements", [])
        retired = previous.get("retired_requirements", [])
        if isinstance(requirements, list):
            for configured_question in questions[index:]:
                for requirement in requirements[:6]:
                    if not (isinstance(requirement, str) and self._retired_evidence(requirement, retired)):
                        evidence = self._known_qualification_detail(configured_question, requirement)
                        if evidence:
                            answers[configured_question] = {"status": "answered", "evidence": evidence}
                            break
        while index < len(questions) and answers.get(questions[index], {}).get("status") == "answered":
            index += 1
        state.update(qualification_answers=answers, qualification_paused=False)
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

        if continuing or answers:
            self._complete_qualification(state, playbook, singular, plural)
            state["qualification_complete"] = True
            state["qualification_pending"] = False

    @staticmethod
    def _customer_evidence(value: Any) -> str:
        # Reuse the existing bounded/private-data rule for customer requirements.
        from service.grounded_conversation import _requirement
        return value.strip() if _requirement(value) else ""

    @classmethod
    def _qualification_answers(cls, previous: Dict[str, Any], questions: List[str]) -> Dict[str, Any]:
        raw = previous.get("qualification_answers")
        if not isinstance(raw, dict):
            return {}
        answers = {}
        for question in questions:
            row = raw.get(question)
            if (isinstance(row, dict) and row.get("status") in {"answered", "unknown", "declined"}
                    and (evidence := cls._customer_evidence(row.get("evidence")))):
                if row["status"] == "answered" and cls._retired_evidence(evidence, previous.get("retired_requirements")):
                    continue
                answers[question] = {"status": row["status"], "evidence": evidence}
        return answers

    @staticmethod
    def _retired_evidence(evidence: str, retired: Any) -> bool:
        if not isinstance(retired, list):
            return False
        # Compare whole tokens, including complete decimal amounts. A short
        # retired quote can occur inside its longer answer (or vice versa),
        # while £10 must not invalidate £100 or £10.50.
        def tokens(value: str) -> List[str]:
            return re.findall(r"\d+(?:[.,]\d+)*|\w+|[£$€]", value.casefold())

        observed = tokens(evidence)
        for row in retired[-6:]:
            if not isinstance(row, str):
                continue
            previous = tokens(row)
            if not observed or not previous:
                continue
            short, long = (observed, previous) if len(observed) <= len(previous) else (previous, observed)
            if any(long[index:index + len(short)] == short for index in range(len(long) - len(short) + 1)):
                return True
        return False

    @classmethod
    def _known_qualification_detail(cls, question: str, requirement: Any) -> str:
        evidence = cls._customer_evidence(requirement)
        if not evidence or _UNKNOWN_ANSWER.search(evidence) or _DECLINED_ANSWER.fullmatch(evidence):
            return ""
        if re.search(r"\b(?:budget|spend)\b", question, re.I):
            if (re.search(r"\b(?:budget|spend)\b", evidence, re.I)
                    and re.search(r"(?:[£$€]\s*\d|\d\s*(?:GBP|USD|EUR)\b)", evidence, re.I)):
                return evidence
        if re.search(r"\b(?:when|deadline|timing|timeframe|completed|completion)\b", question, re.I):
            if re.search(r"\b(?:(?:by|before|after|next|this|within|in)\s+(?:\d+\s+)?"
                         r"(?:days?|weeks?|months?|years?|weekend|monday|tuesday|wednesday|thursday|"
                         r"friday|saturday|sunday)|today|tomorrow)\b", evidence, re.I):
                return evidence
        return ""

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
        if goal in _GOAL_STEPS:
            state.update(stage="convert", **_GOAL_STEPS[goal])
        elif goal == "book_consultation":
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
