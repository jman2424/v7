# handlers/handler_v7.py
from __future__ import annotations

import difflib
import logging
import math
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from brain_v7 import BrainV7
from renderer_v7 import RendererV7
from service.sales_playbook import load_sales_playbook, offering_terms
from service.tenant_sales_context import build_tenant_sales_context, discovery_question
from service.validators import normalize_phone

logger = logging.getLogger("handler_v7")


def _public_product_facts(item: Dict[str, Any], currency: str) -> Dict[str, Any]:
    """Project bounded customer facts without exposing arbitrary nested metadata."""
    fields = ('sku', 'name', 'description', 'price', 'unit', 'stock', 'url')
    facts: Dict[str, Any] = {
        key: value[:1500] if isinstance(value, str) else value
        for key in fields if isinstance((value := item.get(key)), (str, int, float, bool))
        and (type(value) is not float or math.isfinite(value))
    }
    facts['currency'] = currency

    # A missing flag is unknown. A known zero quantity cannot be advertised as
    # in stock, even if an older boolean flag still says otherwise.
    in_stock = item.get('in_stock')
    facts['in_stock'] = in_stock if type(in_stock) is bool else None
    quantity = item.get('stock_quantity')
    if type(quantity) in (int, float) and 0 <= quantity <= 1_000_000_000 and math.isfinite(quantity):
        facts['stock_quantity'] = quantity
        if quantity == 0:
            facts['in_stock'] = False

    def text(value: Any, maximum: int) -> str:
        return ' '.join(value.split())[:maximum] if isinstance(value, str) else ''

    tags = item.get('tags')
    if isinstance(tags, list):
        facts['tags'] = list(dict.fromkeys(tag for value in tags[:40]
                                          if (tag := text(value, 80))))[:20]
    options = item.get('options')
    if isinstance(options, list):
        public_options = []
        for option in options[:40]:
            if (not isinstance(option, dict) or option.get('public') is False
                    or option.get('active') is False):
                continue
            name, value = text(option.get('name'), 80), text(option.get('value'), 160)
            if name and value:
                public_options.append({'name': name, 'value': value})
            if len(public_options) == 20:
                break
        facts['options'] = public_options
    return facts


class MessageHandlerV7:
    """
    V7 handler (crash-proof + smarter routing)

    Main fixes:
    - Real greeting detection only.
    - Smalltalk/meta-AI handled locally.
    - Out-of-scope detection handled cleanly.
    - Delivery / nearest-branch logic preserved.
    - Product typo handling delegated to the tenant catalog search.
    - Better product-ish detection.
    - One safe retry search for empty product results.
    """

    _GREETINGS = {
        "hello", "hi", "hey", "hiya", "yo", "sup",
        "asalam", "assalam", "salam", "asalaam", "salaam",
        "good morning", "good afternoon", "good evening",
    }

    _SMALLTALK = {
        "how are you", "how r u", "hru", "whats up", "what's up",
        "help", "can you help", "can u help", "need help",
        "is this ai", "are you ai", "are you real", "who are you",
        "not ai", "you're not ai", "youre not ai", "u not ai",
        "where is the ai", "were is the ai", "where's the ai", "wheres the ai",
    }

    _OUT_OF_SCOPE_HINTS = (
        "weather", "temperature outside", "forecast", "rain",
        "news", "headlines",
        "sports", "score", "match result",
        "stock", "crypto", "bitcoin",
        "translate this", "homework", "maths", "equation",
        "what time is it in",
    )

    _BUY_WORDS = (
        "price", "prices", "cost", "how much", "cheapest", "cheap", "offer", "deal",
        "recommend", "recommendation", "suggest", "suggestion", "options", "list",
        "full list", "catalog", "catalogue", "product", "products", "item", "items",
        "available", "stock", "buy", "purchase", "shop", "looking for", "need", "want",
        "service", "services", "consultation", "appointment", "quote", "estimate", "booking",
        "book", "hire", "install", "repair",
    )

    _EXPLICIT_SHOPPING_WORDS = (
        "buy", "purchase", "price", "prices", "cost", "how much", "cheapest",
        "offer", "deal", "recommend", "list", "catalog", "catalogue", "available",
        "show", "browse", "view", "products", "items", "in stock", "do you have",
        "have you got", "do you sell", "looking for", "need", "want",
        "service", "services", "consultation", "appointment", "quote", "estimate", "booking",
        "book", "hire", "install", "repair",
    )

    _SEARCH_STOP_WORDS = {
        "a", "an", "and", "any", "available", "buy", "catalog", "catalogue", "do",
        "for", "have", "i", "in", "is", "item", "items", "list", "looking", "me",
        "need", "of", "product", "products", "recommend", "show", "some", "the",
        "to", "want", "what", "with", "you", "your",
    }

    _BROWSE_ALL_PAT = re.compile(
        r"\b(show|browse|list|see|view)?\s*(all|full|entire|whole)?\s*"
        r"(products?|items?|services?|offerings?|catalog|catalogue|range)\b",
        re.I,
    )

    _POSTCODE_FULL = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})\b", re.I)
    _POSTCODE_OUTWARD = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\b", re.I)

    _BRANCH_PHRASES = (
        "nearest branch",
        "nearest store",
        "closest branch",
        "closest store",
        "near me",
        "nearby",
        "which branch",
        "what branch",
        "where is the nearest",
        "where is your nearest",
        "where is the closest",
        "where are you located",
        "what is my nearest branch",
    )

    _DELIVERY_PHRASES = (
        "delivery",
        "deliver",
        "do you deliver",
        "can you deliver",
        "deliver to",
        "deliveries",
        "delivery to",
    )

    _HANDOFF_PHRASES = (
        "speak to someone",
        "speak with someone",
        "talk to someone",
        "talk to a person",
        "human agent",
        "real person",
        "call me back",
        "contact me",
        "customer service",
        "book a consultation",
        "arrange a consultation",
        "book a call",
        "schedule a call",
        "book an appointment",
        "schedule an appointment",
        "arrange an appointment",
        "get a quote",
        "request a quote",
        "request a callback",
    )
    _PHONE_CANDIDATE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
    _EMAIL_CANDIDATE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
    _HANDOFF_NAME_CANDIDATE = re.compile(
        r"\b(?i:my name is|this is|i am|i['’]m)\s+"
        r"([A-Z][A-Za-z'-]*(?:\s+[A-Z][A-Za-z'-]*){0,3})"
    )
    _COMPARISON_REQUEST = re.compile(
        r"\b(?:compare|comparison|difference between|versus)\b|\bvs\.?(?=\s|$)",
        re.I,
    )
    _COMPARISON_SEPARATOR = re.compile(r"\s+(?:and|with|versus|vs\.?)\s+", re.I)
    _STORE_INFO_PHRASES = (
        "how can i contact",
        "how do i contact",
        "contact details",
        "phone number",
        "telephone number",
        "email address",
        "what is your number",
        "what's your number",
        "your website",
        "website address",
        "tell me about your business",
        "about the business",
    )
    _OFFER_REQUEST = re.compile(
        r"\b(?:offers?|deals?|discounts?|promotions?|sales?|specials?|bogo|buy\s+(?:1|one)\s+get\s+(?:1|one))\b",
        re.I,
    )
    _PRICE_REQUEST = re.compile(r"\b(?:price|prices|cost|how much)\b", re.I)
    _SELECTION_NUMBER = re.compile(r"^\s*(?:option\s*)?([1-9]|1[0-2])\s*[.)]?\s*$", re.I)
    _SELECTION_ACTIONS = {
        "compare_or_price_selection",
        "select_available_alternative",
        "select_compared_product",
    }

    def __init__(self, deps: Any):
        self.catalog = getattr(deps, "catalog", None)
        self.policy = getattr(deps, "policy", None)
        self.geo = getattr(deps, "geo", None)
        self.faq = getattr(deps, "faq", None)
        self.offers = getattr(deps, "offers", None)
        self.synonyms = getattr(deps, "synonyms", None)
        self.overrides = getattr(deps, "overrides", None)
        self.logger = getattr(deps, "logger", None)
        self.business_name = str(getattr(deps, "business_name", "") or "").strip()
        profile = getattr(deps, "business_profile", None)
        self.business_profile = profile if isinstance(profile, dict) else {}
        self.rewriter = getattr(deps, "rewriter", None)
        self.sales_playbook = load_sales_playbook(self.overrides)
        self.offering_singular, self.offering_plural = offering_terms(self.sales_playbook)
        self.sales_context = build_tenant_sales_context(
            self.business_profile,
            self.sales_playbook,
            self._catalog_categories(),
        )

        self.business_core = None
        storage = getattr(self.catalog, 'storage', None)
        self.tenant_key = getattr(storage, 'tenant_key', None)
        self.website_knowledge = {}
        self.sales_actions = {}
        self.website_destinations = []
        if storage is not None:
            from service.website_destinations import load
            try:
                self.website_destinations = load(storage, storage.tenant_key)
            except ValueError:
                logger.warning('Invalid website destinations; navigation disabled')
            try:
                knowledge = storage.read_json(storage.tenant_key, 'website_knowledge.json')
                if isinstance(knowledge, dict):
                    self.website_knowledge = knowledge
            except (FileNotFoundError, ValueError):
                pass
            from service.conversion_actions import ActionError, load_actions
            try:
                self.sales_actions = load_actions(storage, storage.tenant_key)
            except ActionError:
                pass
        if storage is not None:
            try:
                storage.read_json(storage.tenant_key, 'business_core.json')
            except FileNotFoundError:
                pass
            else:
                from service.business_core import BusinessCore
                self.business_core = BusinessCore(storage, storage.tenant_key)
                self.sales_context['business_core'] = self.business_core.public_context()

        self.brain = BrainV7(getattr(deps, "openai_client", None))
        tone_style, max_sentences = self._tone_settings()
        self.renderer = RendererV7(
            getattr(deps, "rewriter", None),
            self.business_name,
            tone_style=tone_style,
            max_sentences=max_sentences,
            offering_type=self.sales_playbook["offering_type"],
            business_context=self.sales_context,
        )

    # ------------------------------------------------------------------
    # PUBLIC
    # ------------------------------------------------------------------

    def handle(self, user_text: str, ctx: Any, sess: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.perf_counter()
        user_text = (user_text or "").strip()

        request_id = self._get_request_id(ctx) or str(uuid.uuid4())[:12]
        tenant = getattr(ctx, "tenant", None) or "unknown"
        session_id = getattr(ctx, "session_id", None) or "unknown"
        channel = getattr(ctx, "channel", None) or "unknown"

        session_snapshot = {
            "postcode": (sess or {}).get("postcode"),
            "last_intent": (sess or {}).get("last_intent"),
            "last_category": (sess or {}).get("last_category"),
            "last_sku": (sess or {}).get("last_sku"),
        }
        session_state = {
            "has_postcode": bool(session_snapshot["postcode"]),
            "last_intent": session_snapshot["last_intent"],
            "has_category": bool(session_snapshot["last_category"]),
            "has_sku": bool(session_snapshot["last_sku"]),
        }

        self._info(
            request_id,
            "V7.start",
            tenant=tenant,
            channel=channel,
            session_present=bool(session_id and session_id != "unknown"),
            text_len=len(user_text),
            session_state=session_state,
        )

        try:
            # A handoff is a real saved lead workflow, not a prose-only reply.
            contact = self._handoff_contact(user_text, sess)
            if contact and self._has_pending_handoff(sess):
                return self._wrap_reply(request_id=request_id, t0=t0,
                    reply="Thanks, I’ve recorded those contact details for the team. You can add details about what you need.",
                    intent='handoff_contact_captured', plan=None,
                    facts={'handoff':{'contact_captured':True}}, entities=contact, items=[])
            conversion = self._conversion_action(user_text, channel)
            if conversion:
                action_type, reply_text = conversion
                return self._wrap_reply(
                    request_id=request_id, t0=t0, reply=reply_text,
                    intent=f"{action_type}_request", plan=None,
                    facts={}, entities={}, items=[],
                    actions=[{"type": action_type, "label": {
                        "consultation": "Book consultation", "quote": "Request quote",
                        "callback": "Request callback",
                    }[action_type]}],
                )

            # Explicit requests for a person reach the saved lead workflow.
            # Booking/quote requests above retain their configured action forms.
            if self._explicit_human_request(user_text):
                return self._wrap_reply(request_id=request_id, t0=t0,
                    reply=self._handoff_reply(), intent='human_handoff', plan=None,
                    facts={}, entities={}, items=[])

            # A funded, accounted answer takes precedence over keyword shortcuts.
            # The existing deterministic paths remain the no-credit/provider fallback.
            intelligent = self._grounded_answer(user_text, sess, channel=channel)
            if intelligent:
                return self._wrap_reply(
                    request_id=request_id, t0=t0, reply=intelligent['reply'] if isinstance(intelligent, dict) else intelligent,
                    intent="grounded_answer", plan=None,
                    facts={"source": "tenant_knowledge"}, entities={}, items=[],
                    actions=intelligent.get('actions', []) if isinstance(intelligent, dict) else [],
                    agent=intelligent.get('agent') if isinstance(intelligent, dict) else None,
                )

            from service.platform_offer_knowledge import public_knowledge, automatic_offer_answer
            offer_answer = automatic_offer_answer(user_text, public_knowledge(self.tenant_key))
            if offer_answer:
                return self._wrap_reply(request_id=request_id,t0=t0,reply=offer_answer,
                    intent='faq',plan=None,facts={'source':'current_platform_offer'},entities={},items=[])

            # 0) Greeting only
            if self._is_greeting(user_text):
                reply_text = self._greeting_reply()
                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="greeting",
                    plan=None,
                    facts={},
                    entities={},
                    items=[],
                )

            # 0.5) Smalltalk / meta
            if self._is_smalltalk(user_text):
                reply_text = self._smalltalk_reply(user_text)
                safe_plan = self._simple_plan("smalltalk", "SMALLTALK_REPLY", session_snapshot)
                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="smalltalk",
                    plan=safe_plan,
                    facts={},
                    entities=self._entities_from_plan(safe_plan),
                    items=[],
                )

            # 0.9) Explicit human handoff and voluntary contact details.
            contact = self._handoff_contact(user_text, session_snapshot)
            if contact and self._has_pending_handoff(session_snapshot):
                plan = self._simple_plan("handoff_contact_captured", "HUMAN_HANDOFF", session_snapshot)
                reply_text = (
                    "Thanks, I’ve recorded those contact details for the team. "
                    "You can add any details about what you need that would help them."
                )
                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="handoff_contact_captured",
                    plan=plan,
                    facts={"handoff": {"contact_captured": True}},
                    entities=contact,
                    items=[],
                )

            # Account-support intent must not inherit a previous shopping
            # category or become another recommendation list.
            support_request = bool(re.search(r"\b(?:cancel|cancellation|unsubscribe|refund|complaint)\b", user_text, re.I))
            if support_request:
                faq = self._find_faq(user_text, session_snapshot, request_id=request_id)
                if faq and re.search(r"\b(?:cancel|cancellation|unsubscribe|refund|complaint)\b", faq.get('question', ''), re.I):
                    plan = self._simple_plan("faq", "FAQ_LOOKUP", session_snapshot)
                    facts = {"faq": faq}
                    reply_text = self.renderer.render(user_text=user_text, plan=plan, facts=facts, session=session_snapshot)
                    return self._wrap_reply(request_id=request_id, t0=t0, reply=reply_text,
                                            intent="faq", plan=plan, facts=facts, entities={}, items=[])
            if support_request or self._requests_handoff(user_text):
                plan = self._simple_plan("human_handoff", "HUMAN_HANDOFF", session_snapshot)
                reply_text = self._handoff_reply()
                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="human_handoff",
                    plan=plan,
                    facts={},
                    entities={},
                    items=[],
                )

            # "Offer" can describe a service, rather than a promotion. An
            # exact owner-maintained FAQ can answer that availability question.
            # Current prices, stock, delivery and promotions retain their paths.
            if (re.search(r"\b(?:do|can|could)\s+you\s+offer\b", user_text, re.I)
                    and not self._PRICE_REQUEST.search(user_text)
                    and not re.search(
                        r"\b(?:stock|available|delivery|shipping|collection|pick[ -]?up|"
                        r"offers|deals?|discounts?|promotions?|sales?|specials?|bogo|coupons?)\b",
                        user_text, re.I)):
                service_faq = self._find_faq(user_text, session_snapshot, request_id=request_id)
                if (service_faq and self._normalize_text(service_faq["question"])
                        == self._normalize_text(user_text)):
                    plan = self._simple_plan("faq", "FAQ_LOOKUP", session_snapshot)
                    facts = {"faq": service_faq}
                    reply_text = self.renderer.render(
                        user_text=user_text, plan=plan, facts=facts, session=session_snapshot)
                    return self._wrap_reply(
                        request_id=request_id, t0=t0, reply=reply_text, intent="faq",
                        plan=plan, facts=facts, entities={}, items=[],
                    )

            offers = self._current_offers(user_text)
            if offers is not None:
                plan = self._simple_plan("offers", "SHOW_OFFERS", session_snapshot)
                facts = {"offers": offers}
                reply_text = self.renderer.render(user_text=user_text, plan=plan, facts=facts, session=session_snapshot)
                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="offers",
                    plan=plan,
                    facts=facts,
                    entities={"product_sku": offers.get("matched_product_sku")} if offers.get("matched_product_sku") else {},
                    items=[],
                )

            comparison_items = self._comparison_items(user_text, request_id=request_id)
            if comparison_items is not None:
                plan = self._simple_plan("compare_products", "COMPARE_PRODUCTS", session_snapshot)
                facts = {
                    "comparison": {"items": comparison_items},
                    "items": comparison_items,
                    "currency": self._catalog_currency(),
                }
                reply_text = self.renderer.render(user_text=user_text, plan=plan, facts=facts, session=session_snapshot)
                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="compare_products",
                    plan=plan,
                    facts=facts,
                    entities={"comparison_skus": [item.get("sku") for item in comparison_items]},
                    items=comparison_items,
                )

            selected_product = self._selected_product_from_session(user_text, sess)
            price_product = selected_product or self._price_product_in_text(user_text)
            if price_product and price_product.get("in_stock") is not False:
                sku = str(price_product.get("sku") or "").strip()
                plan = self._simple_plan("price_check", "PRICE_CHECK", session_snapshot)
                plan["sku"] = sku
                facts = {
                    "price": {
                        "sku": sku,
                        "name": str(price_product.get("name") or "").strip(),
                        "price": price_product.get("price"),
                        "unit": str(price_product.get("unit") or "").strip(),
                        "in_stock": price_product.get("in_stock"),
                    },
                    "currency": self._catalog_currency(),
                }
                reply_text = self.renderer.render(user_text=user_text, plan=plan, facts=facts, session=session_snapshot)
                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="price_check",
                    plan=plan,
                    facts=facts,
                    entities={"sku": sku, "product_name": facts["price"]["name"]},
                    items=[],
                )

            unavailable_product = (
                price_product if price_product and price_product.get("in_stock") is False
                else self._unavailable_product_in_text(user_text)
            )
            if unavailable_product:
                alternatives = self._in_stock_alternatives(unavailable_product)
                plan = self._simple_plan("unavailable_product", "SHOW_ALTERNATIVES", session_snapshot)
                facts = {
                    "unavailable_product": unavailable_product,
                    "items": alternatives,
                    "currency": self._catalog_currency(),
                }
                reply_text = self.renderer.render(user_text=user_text, plan=plan, facts=facts, session=session_snapshot)
                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="unavailable_product",
                    plan=plan,
                    facts=facts,
                    entities={
                        "product_sku": unavailable_product.get("sku"),
                        "alternative_skus": [item.get("sku") for item in alternatives],
                    },
                    items=alternatives,
                )

            store_info = self._store_info_answer(user_text)
            if not store_info:
                store_info = self._delivery_information_answer(user_text)
            if store_info:
                plan = self._simple_plan("store_info", "STORE_INFO", session_snapshot)
                facts = {"store_info": {"answer": store_info}}
                reply_text = self.renderer.render(user_text=user_text, plan=plan, facts=facts, session=session_snapshot)
                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="store_info",
                    plan=plan,
                    facts=facts,
                    entities={},
                    items=[],
                )

            # 1) Branch / delivery questions
            if self._looks_like_branch_or_delivery_question(user_text):
                extracted_pc = self._extract_postcode(user_text)
                pc = extracted_pc or session_snapshot.get("postcode")

                if not pc:
                    reply_text = "Sure — what’s your postcode? (e.g. E7 9QS) I’ll tell you delivery + nearest branch."
                    plan = {
                        "intent": "check_delivery",
                        "action": "CHECK_DELIVERY",
                        "category": None,
                        "product_name": None,
                        "postcode": None,
                        "sku": None,
                        "handoff_channel": None,
                        "needs_clarification": True,
                        "clarification_question": "What’s your postcode?",
                        "meta": {"max_items": 0},
                    }
                    return self._wrap_reply(
                        request_id=request_id,
                        t0=t0,
                        reply=reply_text,
                        intent="check_delivery_needs_postcode",
                        plan=plan,
                        facts={},
                        entities={},
                        items=[],
                    )

                plan = {
                    "intent": "check_delivery",
                    "action": "CHECK_DELIVERY",
                    "category": None,
                    "product_name": None,
                    "postcode": pc,
                    "sku": None,
                    "handoff_channel": None,
                    "needs_clarification": False,
                    "clarification_question": "",
                    "meta": {"max_items": 0},
                }
                facts = self._execute_plan(plan, user_text, session_snapshot, request_id=request_id)
                reply_text = self.renderer.render(user_text=user_text, plan=plan, facts=facts, session=session_snapshot)

                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="check_delivery",
                    plan=plan,
                    facts=facts,
                    entities=self._entities_from_plan(plan),
                    items=facts.get("items") or [],
                )

            # 2) Postcode-only => delivery
            extracted_pc = self._extract_postcode(user_text)
            if extracted_pc:
                plan = {
                    "intent": "check_delivery",
                    "action": "CHECK_DELIVERY",
                    "category": None,
                    "product_name": None,
                    "postcode": extracted_pc,
                    "sku": None,
                    "handoff_channel": None,
                    "needs_clarification": False,
                    "clarification_question": "",
                    "meta": {"max_items": 0},
                }
                facts = self._execute_plan(plan, user_text, session_snapshot, request_id=request_id)
                reply_text = self.renderer.render(user_text=user_text, plan=plan, facts=facts, session=session_snapshot)

                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="check_delivery",
                    plan=plan,
                    facts=facts,
                    entities=self._entities_from_plan(plan),
                    items=facts.get("items") or [],
                )

            # 3) Heuristic plan only if product-ish
            plan: Optional[Dict[str, Any]] = None
            plan_from_heuristic = False
            product_query = self._looks_like_product_query(user_text)
            faq = self._find_faq(user_text, session_snapshot, request_id=request_id)
            # Named catalog prices and unavailable items were resolved above.
            # An exact FAQ may still describe pricing for a non-catalog service.
            sales_data_request = bool(re.search(
                r'\b(?:stock|delivery|shipping|collection|pick[ -]?up|offers|deals?|discounts?|promotions?|coupons?)\b',
                user_text, re.I,
            ) or (self._PRICE_REQUEST.search(user_text)
                  and re.search(r"\b(?:do|can|could)\s+you\s+offer\b", user_text, re.I)))
            exact_faq = bool(faq and not sales_data_request
                             and self._normalize_text(faq['question']) == self._normalize_text(user_text))
            if faq and (exact_faq or not (product_query and self._is_explicit_shopping_request(user_text))):
                plan = self._simple_plan("faq", "FAQ_LOOKUP", session_snapshot)
                facts = {"faq": faq}
                reply_text = self.renderer.render(user_text=user_text, plan=plan, facts=facts, session=session_snapshot)
                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="faq",
                    plan=plan,
                    facts=facts,
                    entities={},
                    items=[],
                )

            # Specific customer actions and authoritative price/FAQ answers take
            # precedence over a generic offering-name match.
            if self.business_core:
                selected_ids = self._selected_generic_offering_ids(user_text, sess)
                generic = self.business_core.answer_details(user_text, selected_ids=selected_ids)
                if generic:
                    return self._wrap_generic_reply(generic, request_id=request_id, t0=t0)

            if not re.search(r"\b(price|cost|stock|available|book|schedule|order|buy|purchase|deliver|delivery)\b",
                             user_text, re.I):
                website_answer = self._answer_from_website(user_text)
                if website_answer:
                    return self._wrap_reply(
                        request_id=request_id, t0=t0, reply=website_answer,
                        intent="website_answer", plan=None,
                        facts={"source": "imported_website"}, entities={}, items=[],
                    )

            if product_query:
                plan = self._heuristic_plan(user_text, request_id=request_id)
                plan_from_heuristic = bool(plan)

            # Tenant FAQs and imported facts can cover otherwise unrelated topics.
            if not plan and self._looks_out_of_scope(user_text):
                reply_text = f"I can help with questions about {self._business_scope()}."
                safe_plan = self._simple_plan("out_of_scope", "SMALLTALK_REPLY", session_snapshot)
                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="out_of_scope",
                    plan=safe_plan,
                    facts={},
                    entities=self._entities_from_plan(safe_plan),
                    items=[],
                )

            # 4) Otherwise brain
            if not plan:
                plan = self._safe_plan(user_text=user_text, session=session_snapshot, request_id=request_id)
                plan = self._normalize_plan(plan, user_text=user_text)

            intent_norm = (plan.get("intent") or "unknown").strip().lower()
            action_norm = (plan.get("action") or "").strip().upper()

            # 5) Respect brain smalltalk
            if intent_norm == "smalltalk" or action_norm == "SMALLTALK_REPLY":
                reply_text = self._smalltalk_reply(user_text)
                safe_plan = self._simple_plan("smalltalk", "SMALLTALK_REPLY", session_snapshot)
                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="smalltalk",
                    plan=safe_plan,
                    facts={},
                    entities=self._entities_from_plan(safe_plan),
                    items=[],
                )

            # 6) Unknown but not product-ish
            focused_clarifier = bool(plan.get('needs_clarification') and
                                     self.renderer._safe_clarification_question(plan.get('clarification_question')))
            if intent_norm == "unknown" and not focused_clarifier and not self._looks_like_product_query(user_text):
                reply_text = self._discovery_reply()
                safe_plan = self._simple_plan("unknown", "DO_NOTHING", session_snapshot)
                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="unknown",
                    plan=safe_plan,
                    facts={},
                    entities=self._entities_from_plan(safe_plan),
                    items=[],
                )

            # Model wording selects an offering only after a current public
            # name lookup. The model cannot invent its price or terms.
            native = self._planned_generic_offering(plan)
            if native:
                return self._wrap_generic_reply(native, request_id=request_id, t0=t0, plan=plan)

            # 7) Execute
            facts = self._execute_plan(plan, user_text, session_snapshot, request_id=request_id)

            # 8) Retry if empty search
            if (plan.get("action") or "").strip().upper() == "SEARCH_PRODUCTS":
                if not (facts.get("items") or []):
                    retry = self._retry_search_if_worth_it(plan, user_text=user_text, request_id=request_id)
                    if retry is not None:
                        facts["items"] = retry

            if (plan_from_heuristic and not facts.get('items') and self.business_core
                    and self.business_core.public_context()['offerings']):
                # One semantic fallback after a real catalog miss; successful
                # catalog searches keep their existing local response path.
                semantic_plan = self._normalize_plan(
                    self._safe_plan(user_text, session_snapshot, request_id), user_text,
                )
                native = self._planned_generic_offering(semantic_plan)
                if native:
                    return self._wrap_generic_reply(native, request_id=request_id, t0=t0, plan=semantic_plan)
                if (semantic_plan.get('needs_clarification')
                        and self.renderer._safe_clarification_question(semantic_plan.get('clarification_question'))):
                    plan, facts = semantic_plan, {}

            reply_text = self.renderer.render(user_text=user_text, plan=plan, facts=facts, session=session_snapshot)

            return self._wrap_reply(
                request_id=request_id,
                t0=t0,
                reply=reply_text,
                intent=plan.get("intent"),
                plan=plan,
                facts=facts,
                entities=self._entities_from_plan(plan),
                items=facts.get("items") or [],
            )

        except Exception as e:
            dt_ms = int((time.perf_counter() - t0) * 1000)
            self._exc(request_id, "V7.handle_crash", err=str(e), latency_ms=dt_ms)
            return {
                "reply": "Sorry — I had a technical issue. Please try again.",
                "mode": "v7",
                "intent": "system_error",
                "entities": {},
                "facts": {},
                "ui": {"has_catalog": False, "catalog_items": []},
                "meta": {"request_id": request_id, "latency_ms": dt_ms, "error": "handler_v7_crash"},
            }

    # ------------------------------------------------------------------
    # Local replies
    # ------------------------------------------------------------------

    def _smalltalk_reply(self, user_text: str) -> str:
        t = self._clean_text(user_text)

        if any(x in t for x in ("ai", "bot", "real", "who are you", "where is the ai", "were is the ai")):
            return f"Yes - I'm an AI-powered {self._assistant_label()}. I can help with {self._business_scope()}."

        if "help" in t:
            return f"Sure - tell me what you need. I can help with {self._business_scope()}."

        if any(x in t for x in ("how are you", "how r u", "hru", "whats up", "what's up")):
            return f"I'm ready to help with {self._business_scope()}."

        return f"I'm the {self._assistant_label()}. Ask me about {self._business_scope()}."

    def _grounded_answer(self, question: str, session: Dict[str, Any], *, channel: str = 'web') -> Optional[Dict[str, Any]]:
        from service.grounded_conversation import answer
        client = getattr(self.rewriter, '_client', None)
        if client is None:
            return None
        knowledge = {"business": {key: value for key, value in self.sales_context.items() if key != 'business_core'}}
        from service.platform_offer_knowledge import public_knowledge, public_destinations
        live_offer = public_knowledge(self.tenant_key)
        if live_offer:
            knowledge['current_platform_offer'] = live_offer
        from service.website_knowledge import relevant_passages
        history = session.get('conversation_history', [])
        previous = session.get('sales_agent') if isinstance(session.get('sales_agent'),dict) else {}
        previous_ids = (previous['last_offering_ids'] if 'last_offering_ids' in previous
                        else previous.get('offering_ids', []))
        previous_ids = previous_ids[:3] if isinstance(previous_ids,list) else []
        selected_id = previous.get('selected_offering_id')
        remembered = ([selected_id] if isinstance(selected_id,str) else []) + previous_ids
        # Start with the current question. Old assistant replies used to swamp
        # a new policy question with the previous product/pricing vocabulary.
        pages = relevant_passages(self.website_knowledge, question, limit=6)
        follow_up = len(re.findall(r'\w+', question)) <= 10 and bool(re.search(
            r'\b(?:it|its|they|them|their|that|those|one|ones|option|first|second|third|'
            r'eso|esa|ellos|ellas|primero|segundo|tercero|cela|celui|celle|premier|deuxième|troisième|'
            r'هذا|ذلك|تلك|الأول|الثاني|الثالث)\b|^\s*[1-3١-٣]\s*[.)]?\s*$', question, re.I))
        if follow_up and isinstance(history, list):
            query = question + ' ' + ' '.join(str(row.get('content', ''))[:400]
                for row in history[-4:] if isinstance(row, dict) and row.get('role') == 'user')
            for page in relevant_passages(self.website_knowledge, query, limit=6):
                if len(pages) < 6 and page not in pages:
                    pages.append(page)
        for index, page in enumerate(pages):
            knowledge[f'website:{index}'] = page
        if self.faq:
            for index, row in enumerate(self.faq.best_match(question, top_k=5)):
                if isinstance(row, dict) and row.get('active') is not False and row.get('public') is not False:
                    raw_answer = row.get('a')
                    knowledge[f'matched_faq:{index}'] = {'question': str(row.get('q') or '')[:500],
                                                       'answer': str(raw_answer or '')[:2000],
                                                       'answer_complete': isinstance(raw_answer, str)
                                                       and bool(raw_answer.strip()) and len(raw_answer) <= 2000}
        if self.business_core:
            core = self.business_core.public_context(query=question,
                selected_ids=[key[len('offering:'):] for key in remembered
                              if isinstance(key,str) and key.startswith('offering:')])
            knowledge['business_core'] = {**core, 'offerings':core.get('offerings', [])[:12],
                'locations':core.get('locations', [])[:8], 'business_rules':core.get('business_rules', [])[:8]}
            for offering in knowledge['business_core'].get('offerings', []):
                knowledge['offering:'+offering['id']] = offering
        if self.catalog:
            items = []
            for source_id in dict.fromkeys(value for value in remembered if isinstance(value,str)):
                if source_id.startswith('product:'):
                    item = self.catalog.get_item_by_sku(source_id[len('product:'):])
                    if item:
                        items.append(item)
            items += self.catalog.search(text=question, limit=12)
            items += self.catalog.list_all_items()[:40]
            for sku in (session.get('last_items') or [])[:12]:
                item = self.catalog.get_item_by_sku(sku)
                if item:
                    items.append(item)
            for item in items:
                if not isinstance(item, dict) or item.get('active') is False or item.get('public') is False:
                    continue
                sku = str(item.get('sku') or '')[:120]
                if sku:
                    knowledge['product:' + sku] = _public_product_facts(item, self.catalog.currency())
        if self.faq:
            for index, row in enumerate(self.faq.all()[:40]):
                if isinstance(row, dict) and row.get('active') is not False and row.get('public') is not False:
                    raw_answer = row.get('a')
                    knowledge[f'faq:{index}'] = {'question': str(row.get('q') or '')[:500],
                                               'answer': str(raw_answer or '')[:2000],
                                               'answer_complete': isinstance(raw_answer, str)
                                               and bool(raw_answer.strip()) and len(raw_answer) <= 2000}
        if self.policy:
            knowledge['delivery'] = {'notes': self.policy.delivery_notes(),
                                     'notices': self.policy.service_notices()}
            postcode = self._extract_postcode(question) or session.get('postcode')
            if postcode:
                knowledge['delivery']['matching_rule'] = self.policy.delivery_rule_for(postcode)
                knowledge['delivery']['notices'] = self.policy.service_notices(postcode=postcode)
                summary = self.policy.delivery_summary(postcode)
                rule = knowledge['delivery']['matching_rule'] or {}
                parts = [f'Delivery information for {postcode}: ' +
                         (summary or 'The available rules do not establish delivery terms for this postcode.')]
                parts += [str(value).strip() for value in (rule.get('notes'), knowledge['delivery']['notes'])
                          if isinstance(value, str) and value.strip()]
                parts += knowledge['delivery']['notices']
                knowledge['delivery']['statement'] = '\n'.join(parts)
        if self.geo:
            for index, branch in enumerate(self.geo.branches()[:20]):
                if isinstance(branch, dict) and branch.get('active') is not False:
                    knowledge[f'branch:{index}'] = {key: branch[key] for key in
                        ('name', 'address', 'postcode', 'hours', 'phone', 'url') if key in branch}
        if self.offers:
            for index, offer in enumerate(self.offers.active()[:12]):
                if isinstance(offer, dict):
                    knowledge[f'offer:{index}'] = {key: offer[key] for key in
                        ('title', 'description', 'sku', 'price', 'currency', 'start_date', 'end_date', 'terms') if key in offer}
        from service.website_destinations import public_targets
        destinations = public_targets(self.website_destinations, self.website_knowledge,
                                      self.business_profile.get('website', ''))
        destinations += public_destinations(self.tenant_key, self.website_destinations)
        selected = []
        agent_state = {}
        allowed_actions = [action for action in ('consultation', 'quote', 'callback')
                           if channel == 'web' and isinstance(self.sales_actions.get(action), dict)
                           and self.sales_actions[action].get('enabled') is True]
        previous = session.get('sales_agent') if isinstance(session.get('sales_agent'),dict) else {}
        text = answer(client, getattr(self.rewriter, '_model', 'gpt-4o-mini'), question,
                      knowledge, history, self.renderer.tone_style,
                      destinations=destinations, selected_links=selected,
                      allowed_actions=allowed_actions,
                      memory_settings=session.get('_memory_settings'),
                      agent_context={'playbook':self.sales_playbook,'previous_agent':previous,
                                     'selected_offering_id':previous.get('selected_offering_id'),
                                     'offering_ids':previous.get('offering_ids',[])}, agent_state=agent_state)
        requested_action = agent_state.get('requested_action')
        if (agent_state.get('_validated_grounded') is True and requested_action in allowed_actions):
            # Render an existing authenticated request form. This is only a
            # customer-controlled next step, never an executed model action.
            selected.insert(0, {'type': requested_action, 'label': {
                'consultation': 'Book consultation', 'quote': 'Request quote',
                'callback': 'Request callback',
            }[requested_action]})
        else:
            agent_state.pop('requested_action', None)
        return {'reply': text, 'actions': selected[:3], 'agent':agent_state} if text else None

    def _answer_from_website(self, question: str) -> Optional[str]:
        if not self.website_knowledge or not self.rewriter:
            return None
        answer = getattr(self.rewriter, "answer_from_website", None)
        if not callable(answer):
            return None
        from service.website_knowledge import relevant_passages

        passages = relevant_passages(self.website_knowledge, question)
        return answer(question, passages) if passages else None

    def _conversion_action(self, user_text: str, channel: str) -> Optional[Tuple[str, str]]:
        if channel != "web" or not isinstance(self.sales_actions, dict):
            return None
        text = self._action_request_text(user_text)
        if (re.search(r"\b(cancel|cancellation|reschedule|change|move|refund|existing|already booked|"
                      r"cancelar|cancelación|reprogramar|cambiar|anular|annuler|annulation|reporter|modifier|"
                      r"إلغاء|الغاء|تغيير|إعادة جدولة)\b", text)
                or re.search(r"\bmy (consultation|appointment|demo|meeting|quote|callback)\b", text)):
            return None
        if re.search(r"\b(what|which|when|where|how much|price|cost|tell me about)\b", text):
            return None
        intent = re.search(
            r"\b(book|schedule|arrange|request|need|want|get|set up|sign up for|"
            r"reservar|agendar|organizar|pedir|solicitar|quiero|necesito|gustaría|"
            r"réserver|planifier|organiser|demander|souhaite|veux|voudrais|besoin|"
            r"احجز|أحجز|حجز|أريد|اريد|أحتاج|احتاج|اطلب|طلب)\b", text)
        requests = (
            ("consultation", r"\b(consultation|appointment|demo|meeting|cita|consulta|demostración|reunión|rendez-vous|démo|démonstration|réunion|موعد|استشارة|عرض توضيحي|اجتماع)\b"),
            ("quote", r"\b(quote|quotation|estimate|bulk order|custom pricing|presupuesto|cotización|devis|estimation|عرض سعر|تقدير تكلفة)\b"),
            ("callback", r"\b(call me|call back|callback|speak to (someone|a person|sales|the team)|talk to a human|llámame|llamen|devolver la llamada|rappelez-moi|rappelle-moi|appelez-moi|rappel|اتصل بي|اتصلوا بي|عاود الاتصال)\b"),
        )
        for action_type, pattern in requests:
            settings = self.sales_actions.get(action_type)
            if (not isinstance(settings, dict) or settings.get("enabled") is not True
                    or not re.search(pattern, text) or (action_type != "callback" and not intent)):
                continue
            if action_type == "consultation":
                return action_type, (
                    "Use the form below to choose an available consultation time, or send a request for the team to review. "
                    "A booking is confirmed only after the form succeeds."
                )
            if action_type == "quote":
                return action_type, "Use the form below to describe what you need and request a quote from the team."
            return action_type, "Use the form below to request a callback from the team."
        return None

    def _business_label(self) -> str:
        return self.business_name or "this business"

    def _assistant_label(self) -> str:
        if self.business_name:
            return f"{self.business_name} sales assistant"
        return "sales assistant for this business"

    def _business_scope(self) -> str:
        focus = str(self.sales_context.get("business_focus") or "").strip()
        if focus:
            return focus
        categories = self.sales_context.get("categories") or []
        if isinstance(categories, list):
            labels = [str(category).strip() for category in categories[:3] if str(category).strip()]
            if labels:
                return ", ".join(labels)
        if self.offering_singular == "product":
            return "products, pricing, delivery, and branch details"
        if self.offering_singular == "service":
            return "services, availability, and business details"
        return "offerings, availability, and business details"

    def _opening_question(self) -> str:
        goal = str(self.sales_playbook.get("primary_goal") or "drive_sales")
        if goal == "book_consultation":
            return "What would you like to discuss with the team?"
        if goal == 'book_appointment':
            return 'Which service would you like an appointment for?'
        if goal == 'request_quote':
            return 'What do you need a quote for?'
        if goal == 'start_subscription':
            return 'What would you like your subscription to include?'
        if goal == "capture_leads":
            return "What can the team help you with today?"
        if goal == "answer_questions":
            return "What would you like to know?"
        return discovery_question(self.sales_context, self.offering_singular, self.offering_plural)

    def _greeting_reply(self) -> str:
        focus = str(self.sales_context.get("business_focus") or "").strip()
        proposition = self._primary_value_proposition()
        if focus:
            benefit = f" {proposition}" if proposition else ""
            return f"Hi, I'm the {self._assistant_label()}. I can help with {focus}.{benefit} {self._opening_question()}"
        description = str(self.sales_context.get("about") or "").strip()
        if description:
            return f"Hi, I'm the {self._assistant_label()}. {description} {self._opening_question()}"
        return f"Hi, I'm the {self._assistant_label()}. I can help with {self._business_scope()}. {self._opening_question()}"

    def _discovery_reply(self) -> str:
        value = self._primary_value_proposition()
        lead = f"I can help you explore {self._business_scope()}."
        if value:
            lead = f"{lead} {value}"
        return f"{lead} {self._opening_question()}"

    def _primary_value_proposition(self) -> str:
        propositions = self.sales_context.get("value_propositions") or []
        if not isinstance(propositions, list) or not propositions:
            return ""
        return str(propositions[0] or "").strip()

    def _handoff_reply(self) -> str:
        configured = str(self.sales_playbook.get("handoff_message") or "").strip()
        if configured:
            # A business may use an external contact form or email handoff.
            # Do not force every tenant to collect contact details in chat.
            return configured
        return "Please send a phone number or email, plus a short note about what you need, so the team can follow up."

    def _tone_settings(self) -> Tuple[str, int]:
        style = "friendly"
        max_sentences = 2
        if self.overrides:
            try:
                candidate = str(self.overrides.get("tone.style") or style).strip().lower()
                if candidate in {"friendly", "professional", "concise"}:
                    style = candidate
                max_sentences = int(self.overrides.get("tone.max_sentences") or max_sentences)
            except (TypeError, ValueError):
                max_sentences = 2
        return style, min(max(max_sentences, 1), 4)

    def _simple_plan(self, intent: str, action: str, session: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "intent": intent,
            "action": action,
            "category": None,
            "product_name": None,
            "postcode": session.get("postcode"),
            "sku": session.get("last_sku"),
            "handoff_channel": None,
            "needs_clarification": False,
            "clarification_question": "",
            "meta": {"max_items": 0},
        }

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    def _looks_out_of_scope(self, text: str) -> bool:
        t = self._clean_text(text)
        if not t:
            return False
        hints = [hint for hint in self._OUT_OF_SCOPE_HINTS
                 if re.search(r"\b" + re.escape(hint) + r"\b", t)]
        if not hints or self._looks_like_product_query(text):
            return False
        descriptions = [str(self.sales_context.get(key) or "")
                        for key in ("name", "about", "business_focus", "categories")]
        pages = self.website_knowledge.get("pages", [])
        if isinstance(pages, list):
            descriptions.extend(str(page.get("title") or "") + " " + str(page.get("text") or "")
                                for page in pages if isinstance(page, dict))
        tenant_scope = self._clean_text(" ".join(descriptions))
        return any(not re.search(r"\b" + re.escape(hint) + r"\b", tenant_scope)
                   for hint in hints)

    def _looks_like_branch_or_delivery_question(self, text: str) -> bool:
        t = self._clean_text(text)
        if not t:
            return False

        for p in self._BRANCH_PHRASES:
            if p in t:
                return True
        for p in self._DELIVERY_PHRASES:
            if p in t:
                return True

        if "nearest" in t and ("branch" in t or "store" in t):
            return True
        if "closest" in t and ("branch" in t or "store" in t):
            return True
        if "deliver" in t or "delivery" in t:
            return True

        return False

    def _is_greeting(self, text: str) -> bool:
        t = self._clean_text(text)
        if not t:
            return False

        if t in self._GREETINGS:
            return True

        toks = t.split()
        if len(toks) <= 2:
            for g in self._GREETINGS:
                if t.startswith(g + " "):
                    return True

        gmatch = difflib.get_close_matches(t, list(self._GREETINGS), n=1, cutoff=0.88)
        return bool(gmatch)

    def _is_smalltalk(self, text: str) -> bool:
        t = self._clean_text(text)
        if not t:
            return False
        return t in self._SMALLTALK

    def _looks_like_product_query(self, user_text: str) -> bool:
        t = self._normalize_text(user_text)
        if not t:
            return False

        if self._is_smalltalk(t):
            return False

        if self.catalog:
            try:
                if self.catalog.search(text=t, limit=1):
                    return True
            except Exception:
                logger.debug("V7 catalog probe failed", exc_info=True)

        if any(w in t for w in self._BUY_WORDS):
            return True
        if re.search(r"[$£€]", user_text) or re.search(r"\b(under|below|less than)\b", t):
            return True

        toks = t.split()
        if len(toks) == 1:
            tok = toks[0]
            if tok in {"ai", "bot"}:
                return False

        return False

    def _is_explicit_shopping_request(self, user_text: str) -> bool:
        text = self._clean_text(user_text)
        return any(word in text for word in self._EXPLICIT_SHOPPING_WORDS)

    def _requests_handoff(self, user_text: str) -> bool:
        text = self._clean_text(self._action_request_text(user_text))
        if any(phrase in text for phrase in self._HANDOFF_PHRASES):
            return True
        subscriptions = self.sales_playbook.get('primary_goal') == 'start_subscription'
        if self.business_core and not subscriptions:
            subscriptions = any(row.get('type') == 'subscription'
                                for row in self.business_core.public_context()['offerings'])
        return bool(subscriptions and re.search(
            r'\b(?:start|join|begin|discuss|sign up for|subscribe to)\s+(?:a |the |your )?(?:subscription|membership|plan)\b',
            text,
        ))

    @staticmethod
    def _action_request_text(user_text: str) -> str:
        """Keep affirmative request clauses for shortcuts, never change AI input.

        Negating a demo or callback must not open its form before the model can
        answer. Scope that exclusion to its clause so a separate positive request
        still works, including when the customer has no website or account yet.
        """
        clauses = re.split(
            r"[,،;.!?\n]+|\b(?:but|however|instead|rather|pero|sino|mais|plutôt|لكن|بل)\b|"
            r"\band\s+(?=(?:can|could|please|i (?:want|need|would)|book|request|get|send)\b)",
            str(user_text or '').casefold(),
        )
        negative = re.compile(
            r"\b(?:don['’]?t|do not|cannot|can['’]?t|never|not(?: to)?|no need to)\s+"
            r"(?:(?:really|actually|please)\s+)?(?:want|need|wish|plan|intend|like|"
            r"call|contact|book|schedule|arrange|request|get|send|speak|talk|chat)\b|"
            r"\b(?:no|without)\s+(?:(?:a|an|any|more|another)\s+)?"
            r"(?:demo|appointment|consultation|meeting|quote|quotation|estimate|callback|call|contact|human|person)\b|"
            r"\bnot\s+(?:interested|ready|looking)\b|\bno need(?:\s+(?:for|to))?\b|"
            r"\b(?:no thanks|not now|stop calling|stop contacting)\b|"
            r"\bno\s+(?:quiero|necesito|deseo|llames|llamen|contactes|contacten|reservar|agendar)\b|"
            r"\bsin\s+(?:cita|consulta|presupuesto|llamada)\b|"
            r"\b(?:ne|n['’])(?:\s*[\w'’]+){0,4}\s+pas\b|"
            r"\b(?:pas de|sans)\s+(?:démo|consultation|rendez-vous|devis|rappel)\b|"
            r"(?:لا|لن)\s+(?:أريد|اريد|أحتاج|احتاج|تتصل|تتصلوا|تحجز|تطلب|تتواصل)|"
            r"(?:بدون|دون)\s+(?:موعد|استشارة|اتصال|عرض سعر)", re.I,
        )
        informational = re.compile(r"^(?:do i need|what is|how does|tengo que|qué es|qu['’]est-ce|هل يجب)\b")
        return ' '.join(clause.strip() for clause in clauses
                        if clause.strip() and not negative.search(clause)
                        and not informational.match(clause.strip()))

    @classmethod
    def _explicit_human_request(cls, user_text: str) -> bool:
        clauses = cls._action_request_text(user_text)
        # These ask about the need or meaning of a handoff, rather than asking
        # us to collect contact details. Other business questions go to AI too.
        if re.match(r"^(?:do i need|what is|how does|tengo que|qué es|qu['’]est-ce|هل يجب)\b", clauses):
            return False
        return bool(re.search(
            r'\b(?:talk|speak|chat)\s+(?:to|with)\s+(?:a |the |your )?(?:human|person|someone|team|staff)|'
            r'\b(?:call me back|contact me|human agent|real person)\b|'
            r'\b(?:hablar|chatear|comunicarme)\s+con\s+(?:(?:una?|el|tu)\s+)?(?:persona|alguien|equipo|humano|agente)\b|'
            r'\b(?:parler|discuter)\s+(?:avec|à)\s+(?:(?:un|une|le|la|votre)\s+)?(?:personne|humain|équipe|conseiller)\b|'
            r'(?:التحدث مع|التكلم مع|أكلم|اكلم)\s+(?:شخص|إنسان|انسان|موظف|الفريق|أحد)', clauses,
        ))

    def _store_info_answer(self, user_text: str) -> Optional[str]:
        text = self._clean_text(user_text)
        if not text:
            return None

        certifications = self.business_profile.get("certifications") or []
        if (not re.search(r"\b(buy|purchase|price|prices|products?|items?|catalogue|catalog|sell)\b", text)
                and re.search(r"\b(certifications?|certified|accredited|accreditations?|inspected)\b", text)):
            listed = [item.strip() for item in certifications if isinstance(item, str) and item.strip()]
            if listed:
                return "The business lists these certifications: " + ", ".join(listed) + "."
        social = self.business_profile.get("social") or {}
        if isinstance(social, dict):
            requested = [key for key in social if key.lower() in text or "social media" in text]
            links = [f"{key}: {social[key]}" for key in requested if isinstance(social[key], str) and social[key].strip()]
            if links:
                return "You can find the business on " + "; ".join(links) + "."

        if self.geo and re.search(r"\b(opening hours|open hours|business hours|what time.*(?:open|close))\b", text):
            branches = self.geo.branches()
            named = [branch for branch in branches if str(branch.get("name") or "").strip()
                     and str(branch["name"]).casefold() in text.casefold()]
            selected = named or branches
            details = []
            for branch in selected[:3]:
                hours = branch.get("hours") or {}
                if isinstance(hours, dict) and hours:
                    schedule = "; ".join(f"{day}: {value}" for day, value in hours.items() if value)
                    if schedule:
                        details.append(f"{branch.get('name') or branch.get('id')}: {schedule}")
            if details:
                if not named and len(branches) > 3:
                    details.append("For another branch, tell me its name.")
                return "Opening hours:\n" + "\n".join(details)

        is_contact_question = (
            any(phrase in text for phrase in self._STORE_INFO_PHRASES)
            or bool(re.fullmatch(r'(?:contact|phone|telephone|email|website)(?: details| address| number)?', text))
            or bool(re.search(r'\b(?:contact|phone|telephone|email)\s+(?:you|the team|your team|someone)\b', text))
        )
        is_about_question = "about" in text and any(word in text for word in ("business", "company", "store"))
        if not is_contact_question and not is_about_question:
            return None

        name = str(self.business_profile.get("name") or self.business_name or "the business").strip()
        phone = str(self.business_profile.get("phone") or "").strip()
        email = str(self.business_profile.get("email") or "").strip()
        website = str(self.business_profile.get("website") or "").strip()
        about = str(self.business_profile.get("about") or "").strip()

        if is_about_question and about:
            return about

        if "website" in text and website:
            return f"{name}'s website is {website}."

        contact_options: List[str] = []
        if phone:
            contact_options.append(f"phone at {phone}")
        if email:
            contact_options.append(f"email at {email}")
        if contact_options:
            if len(contact_options) == 1:
                answer = f"You can contact {name} by {contact_options[0]}."
            else:
                answer = f"You can contact {name} by {contact_options[0]} or {contact_options[1]}."
            if website and "website" not in text:
                answer = f"{answer} You can also visit {website}."
            return answer

        return "Contact details are not configured for this business yet."

    def _delivery_information_answer(self, user_text: str) -> Optional[str]:
        """Answer configured general policy questions before requesting a postcode."""
        if not self.policy:
            return None
        text = self._clean_text(user_text)
        collection = any(term in text for term in (
            "click and collect", "click & collect", "can i collect", "can we collect",
            "do you offer collection", "pick up", "pickup",
        ))
        policy_question = any(term in text for term in (
            "delivery notes", "delivery policy", "delivery rules", "shipping policy",
            "free delivery", "delivery exceptions", "service exceptions", "holiday delivery",
        ))
        date_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", user_text)
        dated_delivery = bool(date_match and ("deliver" in text or collection))
        if not collection and (self._extract_postcode(user_text) or not (policy_question or dated_delivery)):
            return None
        parts = []
        if collection:
            parts.append("Click and collect is available." if self.policy.click_and_collect()
                         else "Click and collect is not currently available.")
        notes = self.policy.delivery_notes()
        if notes and not collection:
            parts.append("Delivery notes: " + notes)
        notices = self.policy.service_notices(date_match.group(0) if date_match else None)
        parts.extend("Service notice — " + note for note in notices)
        if not parts:
            return None
        if not collection:
            parts.append("Share your postcode to check the standard delivery fee and minimum order for your area.")
        return "\n".join(parts)

    def _current_offers(self, user_text: str) -> Optional[Dict[str, Any]]:
        """Return only current tenant offers, optionally scoped to a named product."""
        if (re.search(r"\b(?:do|can|could)\s+you\s+offer\b", user_text, re.I)
                and not re.search(
                    r"\b(?:offers|deals?|discounts?|promotions?|sales?|specials?|bogo|coupons?)\b",
                    user_text, re.I)):
            # Service/product availability belongs to tenant facts or catalog,
            # even when no exact FAQ exists. Only explicit promotions use offers.
            return None
        if not self._OFFER_REQUEST.search(user_text or ""):
            return None

        active: List[Dict[str, Any]] = []
        if self.offers:
            try:
                active = [offer for offer in self.offers.active() if isinstance(offer, dict)]
            except Exception:
                logger.exception("V7 offer lookup failed")

        product = self._offer_product_in_text(user_text)
        if product:
            sku = str(product.get("sku") or "").strip()
            active = [
                offer
                for offer in active
                if not offer.get("product_skus") or sku in offer.get("product_skus", [])
            ]
            return {
                "items": active,
                "matched_product_name": str(product.get("name") or "").strip(),
                "matched_product_sku": sku,
            }
        return {"items": active}

    def _offer_product_in_text(self, user_text: str) -> Optional[Dict[str, Any]]:
        if not self.catalog:
            return None
        text = self._normalize_text(user_text)
        if not text:
            return None
        try:
            candidates = self.catalog.list_all_items()
        except Exception:
            return None

        matches: List[Tuple[int, Dict[str, Any]]] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            name = self._normalize_text(str(item.get("name") or ""))
            if name and name in text:
                matches.append((len(name), item))
        return max(matches, key=lambda pair: pair[0])[1] if matches else None

    def _exact_catalog_item_in_text(self, user_text: str) -> Optional[Dict[str, Any]]:
        """Match an explicitly named catalog product or SKU without fuzzy guessing."""
        if not self.catalog:
            return None

        text = self._normalize_text(user_text)
        if not text:
            return None

        try:
            candidates = self.catalog.list_all_items()
        except Exception:
            return None

        matches: List[Tuple[int, Dict[str, Any]]] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            name = self._normalize_text(str(item.get("name") or ""))
            sku = self._normalize_text(str(item.get("sku") or ""))
            for identifier in (name, sku):
                if not identifier or len(identifier) < 3:
                    continue
                if re.search(rf"(?<!\w){re.escape(identifier)}(?!\w)", text):
                    matches.append((len(identifier), item))
                    break

        return max(matches, key=lambda pair: pair[0])[1] if matches else None

    def _price_product_in_text(self, user_text: str) -> Optional[Dict[str, Any]]:
        if not self._PRICE_REQUEST.search(user_text or ""):
            return None
        return self._exact_catalog_item_in_text(user_text)

    def _selected_generic_offering_ids(self, user_text: str, session: Dict[str, Any]) -> List[str]:
        """Interpret a choice only against the session's prior public results."""
        if session.get('last_items_source') != 'business_core':
            return []
        agent = session.get('sales_agent') if isinstance(session.get('sales_agent'), dict) else {}
        if agent.get('next_action') not in self._SELECTION_ACTIONS:
            return []
        previous = session.get('last_items')
        if not isinstance(previous, list):
            return []
        identifiers = [identifier for identifier in previous[:12] if isinstance(identifier, str)]
        number = self._SELECTION_NUMBER.match(user_text or '')
        if number and int(number.group(1)) <= len(identifiers):
            return [identifiers[int(number.group(1)) - 1]]
        if len(identifiers) == 1 and re.fullmatch(
            r"\s*(?:how much(?: is (?:it|that|this))?|what(?:'s| is) (?:its|the) price)\s*[?.!]*\s*",
            user_text or '', re.I,
        ):
            return identifiers
        return []

    def _selected_product_from_session(self, user_text: str, session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Resolve a click or numbered choice only within the current session's last results."""
        if session.get('last_items_source') == 'business_core':
            return None
        if not self.catalog:
            return None
        agent = session.get("sales_agent") if isinstance(session.get("sales_agent"), dict) else {}
        if agent.get("next_action") not in self._SELECTION_ACTIONS:
            return None

        last_items = session.get("last_items")
        if not isinstance(last_items, list) or not last_items:
            return None
        skus = [str(sku).strip() for sku in last_items[:12] if str(sku).strip()]
        if not skus:
            return None

        if len(skus) == 1 and re.fullmatch(
            r"\s*(?:how much(?: is (?:it|that|this))?|what(?:'s| is) (?:its|the) price)\s*[?.!]*\s*",
            user_text or "", re.I,
        ):
            return self.catalog.get_item_by_sku(skus[0])

        number_match = self._SELECTION_NUMBER.match(user_text or "")
        if number_match:
            index = int(number_match.group(1)) - 1
            if 0 <= index < len(skus):
                return self.catalog.get_item_by_sku(skus[index])
            return None

        selected_text = self._normalize_text(user_text)
        if not selected_text:
            return None
        for sku in skus:
            item = self.catalog.get_item_by_sku(sku)
            if not isinstance(item, dict):
                continue
            name = self._normalize_text(str(item.get("name") or ""))
            item_sku = self._normalize_text(str(item.get("sku") or ""))
            if selected_text in {name, item_sku}:
                return item
        return None

    def _unavailable_product_in_text(self, user_text: str) -> Optional[Dict[str, Any]]:
        item = self._exact_catalog_item_in_text(user_text)
        return item if item and item.get("in_stock") is False else None

    def _in_stock_alternatives(self, unavailable_item: Dict[str, Any], *, limit: int = 3) -> List[Dict[str, Any]]:
        """Return related, tenant-catalog alternatives only when they are in stock."""
        if not self.catalog:
            return []

        unavailable_sku = str(unavailable_item.get("sku") or "").strip()
        category_id = str(unavailable_item.get("_category_id") or "").strip()
        unavailable_tags = {
            str(tag).strip().lower()
            for tag in (unavailable_item.get("_norm_tags") or unavailable_item.get("tags") or [])
            if str(tag).strip()
        }
        try:
            unavailable_price = float(unavailable_item.get("price"))
        except (TypeError, ValueError):
            unavailable_price = None

        try:
            candidates = self.catalog.list_all_items()
        except Exception:
            return []

        same_category: List[Dict[str, Any]] = []
        shared_tag_matches: List[Dict[str, Any]] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            if str(item.get("sku") or "").strip() == unavailable_sku or item.get("in_stock") is not True:
                continue

            item_category = str(item.get("_category_id") or "").strip()
            item_tags = {
                str(tag).strip().lower()
                for tag in (item.get("_norm_tags") or item.get("tags") or [])
                if str(tag).strip()
            }
            if category_id and item_category == category_id:
                same_category.append(item)
            elif unavailable_tags.intersection(item_tags):
                shared_tag_matches.append(item)

        related = same_category or shared_tag_matches

        def rank(item: Dict[str, Any]) -> Tuple[int, float, str]:
            item_tags = {
                str(tag).strip().lower()
                for tag in (item.get("_norm_tags") or item.get("tags") or [])
                if str(tag).strip()
            }
            shared_tags = len(unavailable_tags.intersection(item_tags))
            try:
                item_price = float(item.get("price"))
            except (TypeError, ValueError):
                item_price = unavailable_price if unavailable_price is not None else 0.0
            price_gap = abs(item_price - unavailable_price) if unavailable_price is not None else 0.0
            return (-shared_tags, price_gap, str(item.get("name") or "").casefold())

        return sorted(related, key=rank)[:limit]

    def _comparison_items(self, user_text: str, *, request_id: str) -> Optional[List[Dict[str, Any]]]:
        if not self._COMPARISON_REQUEST.search(user_text or ""):
            return None

        if not self.catalog:
            return []

        request_match = re.search(r"\b(?:compare|comparison|difference between)\b", user_text, re.I)
        candidates_text = user_text[request_match.end() :] if request_match else user_text
        product_queries = [
            re.sub(r"^(?:the|a|an)\s+", "", value.strip(" ?!.,"), flags=re.I)
            for value in self._COMPARISON_SEPARATOR.split(candidates_text)
            if value.strip(" ?!.,")
        ]
        if len(product_queries) < 2:
            return []

        items: List[Dict[str, Any]] = []
        seen_skus = set()
        for query in product_queries[:2]:
            matches = self._catalog_search_safe(request_id, query=query, tags=[], limit=3)
            if not matches:
                return []
            item = matches[0]
            sku = str(item.get("sku") or "")
            if not sku or sku in seen_skus:
                return []
            seen_skus.add(sku)
            items.append(item)

        return items

    @staticmethod
    def _has_pending_handoff(session: Dict[str, Any]) -> bool:
        if str(session.get("last_intent") or "").strip().lower() in {
            "human_handoff",
            "handoff_contact_captured",
        }:
            return True
        agent = session.get("sales_agent")
        return isinstance(agent, dict) and agent.get("stage") == "handoff"

    @classmethod
    def _handoff_contact(cls, user_text: str, session: Dict[str, Any]) -> Dict[str, str]:
        del session
        contact: Dict[str, str] = {}
        phone_match = cls._PHONE_CANDIDATE.search(user_text or "")
        if phone_match:
            phone = normalize_phone(phone_match.group(0))
            if phone:
                contact["phone"] = phone

        email_match = cls._EMAIL_CANDIDATE.search(user_text or "")
        if email_match:
            contact["email"] = email_match.group(0).lower()

        name_match = cls._HANDOFF_NAME_CANDIDATE.search(user_text or "")
        if name_match:
            contact["name"] = " ".join(name_match.group(1).split())
        return contact

    def _find_faq(
        self,
        user_text: str,
        session: Dict[str, Any],
        *,
        request_id: str,
    ) -> Optional[Dict[str, str]]:
        """Find and safely render a tenant FAQ before asking the model to infer it."""
        if not self.faq:
            return None

        try:
            matches = self.faq.best_match(
                user_text,
                hint_tags=self._token_tags(user_text),
                min_sim=0.45,
            )
        except Exception as exc:
            self._exc(request_id, "V7.faq_lookup_failed", err=str(exc))
            return None

        if not matches or not isinstance(matches[0], dict):
            return None

        entry = matches[0]
        placeholders: Dict[str, str] = {}
        if self.business_name:
            placeholders["business_name"] = self.business_name

        postcode = self._normalize_postcode(str(session.get("postcode") or ""))
        if postcode:
            placeholders["postcode"] = postcode
            if self.policy:
                try:
                    placeholders["delivery_summary"] = self.policy.delivery_summary(postcode) or ""
                except Exception as exc:
                    self._exc(request_id, "V7.faq_delivery_summary_failed", err=str(exc))

        answer = self.faq.render_answer(entry, placeholders).strip()
        if not answer:
            return None
        return {"question": str(entry.get("q") or ""), "answer": answer}

    # ------------------------------------------------------------------
    # Retry search
    # ------------------------------------------------------------------

    def _retry_search_if_worth_it(
        self,
        plan: Dict[str, Any],
        *,
        user_text: str,
        request_id: str,
    ) -> Optional[List[Dict[str, Any]]]:
        if not self.catalog:
            return None

        meta = plan.get("meta") or {}
        q = (plan.get("product_name") or user_text or "").strip()
        q_clean = self._normalize_text(q)

        tokens = [t for t in q_clean.split() if t]
        if not tokens or len(tokens) > 3:
            return None

        try:
            limit = int(meta.get("max_items") or 12)
        except Exception:
            limit = 12

        for token in reversed(tokens):
            if token in self._SEARCH_STOP_WORDS:
                continue
            items = self._catalog_search_safe(request_id, query=token, tags=[token], limit=limit)
            if items:
                self._info(request_id, "V7.catalog.retry", token=token, limit=limit)
                return items
        return None

    # ------------------------------------------------------------------
    # Wrappers / request helpers
    # ------------------------------------------------------------------

    def _planned_generic_offering(self, plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Resolve a model-selected name to active local facts, never inferred terms."""
        if not self.business_core or plan.get('needs_clarification'):
            return None
        if str(plan.get('action') or '').upper() not in {'SEARCH_PRODUCTS', 'PRICE_CHECK'}:
            return None
        name = plan.get('product_name')
        if not isinstance(name, str) or not name.strip() or len(name) > 240:
            return None
        # A current retail record retains its existing price and availability path.
        if self._exact_catalog_item_in_text(name):
            return None
        normalized_name = ' '.join(name.casefold().split())
        rows = self.business_core.document()['offerings']
        identifiers = [row['id'] for row in rows
                       if row['active'] and ' '.join(row['name'].casefold().split()) == normalized_name]
        if not identifiers:
            return None
        return self.business_core.answer_details(name, selected_ids=identifiers)

    def _wrap_generic_reply(
        self, generic: Dict[str, Any], *, request_id: str, t0: float,
        plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        offerings = generic['offerings']
        facts = {
            'items': offerings,
            'business_knowledge': {
                'source': 'business_core',
                'locations': generic['locations'],
                'business_rules': generic['business_rules'],
            },
        }
        entities = {'offering_ids': [item['id'] for item in offerings]}
        if len(offerings) == 1:
            entities['offering_id'] = offerings[0]['id']
        return self._wrap_reply(
            request_id=request_id, t0=t0, reply=generic['reply'],
            intent='business_knowledge', plan=plan, facts=facts,
            entities=entities, items=[],
        )

    def _wrap_reply(
        self,
        *,
        request_id: str,
        t0: float,
        reply: str,
        intent: Optional[str],
        plan: Optional[Dict[str, Any]],
        facts: Dict[str, Any],
        entities: Dict[str, Any],
        items: List[Dict[str, Any]],
        actions: Optional[List[Dict[str, str]]] = None,
        agent: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        dt_ms = int((time.perf_counter() - t0) * 1000)
        safe_facts = dict(facts or {})
        safe_facts.setdefault(
            "sales_context",
            {
                "categories": list(self.sales_context.get("categories") or []),
                "offering_type": self.sales_playbook["offering_type"],
            },
        )
        ui = {
            "has_catalog": bool(items),
            "catalog_items": self._format_items_for_ui(items or []),
        }
        result = {
            "reply": reply,
            "mode": "v7",
            "intent": intent or "unknown",
            "entities": entities or {},
            "facts": safe_facts,
            "ui": ui,
            "meta": {"request_id": request_id, "latency_ms": dt_ms},
        }
        if actions:
            result["actions"] = actions
        if agent:
            result['agent'] = agent
        return result

    def _catalog_categories(self) -> List[Dict[str, Any]]:
        if not self.catalog:
            return []
        try:
            categories = self.catalog.categories()
        except Exception:
            return []
        return [category for category in categories if isinstance(category, dict)]

    def _get_request_id(self, ctx: Any) -> Optional[str]:
        try:
            md = getattr(ctx, "metadata", None) or {}
            if isinstance(md, dict):
                return md.get("rid") or md.get("request_id")
        except Exception:
            return None
        return None

    # ------------------------------------------------------------------
    # Postcodes
    # ------------------------------------------------------------------

    def _normalize_postcode(self, text: str) -> Optional[str]:
        if not text:
            return None
        raw = text.strip().upper()

        m = self._POSTCODE_FULL.search(raw)
        if m:
            return f"{m.group(1)} {m.group(2)}"

        m2 = self._POSTCODE_OUTWARD.fullmatch(raw)
        if m2:
            return m2.group(1)

        return None

    def _extract_postcode(self, user_text: str) -> Optional[str]:
        if not user_text:
            return None

        s = user_text.strip().upper()

        m = self._POSTCODE_FULL.search(s)
        if m:
            return f"{m.group(1)} {m.group(2)}"

        compact = re.sub(r"[^A-Z0-9]", "", s)
        pc = self._normalize_postcode(compact)
        if pc:
            if len(user_text.split()) <= 4 or "POSTCODE" in s or "DELIVERY" in s or "NEAREST" in s or "BRANCH" in s:
                return pc

        return None

    # ------------------------------------------------------------------
    # Query building / plans
    # ------------------------------------------------------------------

    def _parse_modifiers(self, text: str) -> Dict[str, Any]:
        t = self._clean_text(text)

        sort = None
        if re.search(r"\b(cheapest|chepest|cheap|lowest|low)\b", t):
            sort = "price_asc"
        if re.search(r"\b(most expensive|highest|expensive|premium)\b", t):
            sort = "price_desc"

        max_price = None
        m = re.search(r"\b(under|below|less than)\s*£?\s*(\d+(\.\d+)?)\b", t)
        if m:
            try:
                max_price = float(m.group(2))
            except Exception:
                max_price = None

        return {"sort": sort, "max_price": max_price, "tags": []}

    def _required_terms_from_text(self, text: str) -> List[str]:
        t = self._normalize_text(text)
        if not t:
            return []
        return [
            token
            for token in t.split()
            if token not in self._SEARCH_STOP_WORDS and self._catalog_has_match(token)
        ]

    def _strip_modifier_words(self, text: str) -> str:
        s = self._normalize_text(text)
        s = re.sub(
            r"\b(cheapest|chepest|cheap|lowest|low|most|expensive|highest|premium|best|"
            r"under|below|less|than)\b",
            " ",
            s,
        )
        s = re.sub(r"[$£€]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _heuristic_plan(self, user_text: str, request_id: str) -> Optional[Dict[str, Any]]:
        t = self._normalize_text(user_text)
        if not t:
            return None

        mods = self._parse_modifiers(t)
        required = self._required_terms_from_text(t)
        browse_all = bool(self._BROWSE_ALL_PAT.search(t))

        core = "" if browse_all else (self._strip_modifier_words(t) or t)
        core = self._normalize_text(core)

        tags = self._token_tags(core)
        for x in mods.get("tags") or []:
            if x not in tags:
                tags.append(x)

        meta = {
            "max_items": 12,
            "search_tags": tags,
            "sort": mods.get("sort"),
            "max_price": mods.get("max_price"),
            "required_terms": required,
            "browse_all": browse_all,
            "search_scope": "full_store" if browse_all else "top_picks",
            "item_level": False,
            "wants_chunking": browse_all,
        }

        return {
            "intent": "search_product",
            "action": "SEARCH_PRODUCTS",
            "category": None,
            "product_name": core or None,
            "postcode": None,
            "sku": None,
            "handoff_channel": None,
            "needs_clarification": False,
            "clarification_question": "",
            "meta": meta,
        }

    def _safe_plan(self, user_text: str, session: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        try:
            # BrainV7 allowlists and bounds the public planning context before
            # including it in an external model request.
            hints: Dict[str, Any] = {
                "business": self.sales_context,
                "categories": self._catalog_categories(),
            }

            plan = self.brain.plan(
                user_text=user_text,
                session=session,
                history=[],
                hints=hints,
            )
            if not isinstance(plan, dict):
                return {"intent": "unknown", "action": "DO_NOTHING", "meta": {"max_items": 12}}
            return plan
        except Exception as e:
            self._exc(request_id, "V7.brain_plan_failed", err=str(e))
            return {"intent": "unknown", "action": "DO_NOTHING", "meta": {"max_items": 12}}

    def _normalize_plan(self, plan: Dict[str, Any], user_text: str) -> Dict[str, Any]:
        p = dict(plan or {})
        action = (p.get("action") or "").strip().upper()

        category = p.get("category")
        product_name = p.get("product_name")

        if p.get("postcode"):
            p["postcode"] = self._normalize_postcode(str(p["postcode"])) or p["postcode"]

        if (category or product_name) and action in {"", "DO_NOTHING"}:
            p["action"] = "SEARCH_PRODUCTS"
            if (p.get("intent") or "").strip().lower() in {"", "unknown"}:
                p["intent"] = "browse_category" if category and not product_name else "search_product"

        focused_question = self.renderer._safe_clarification_question(p.get('clarification_question'))
        if action == 'ASK_SLOT' and focused_question:
            p['needs_clarification'] = True
        if p.get("needs_clarification") and not focused_question and self._looks_like_product_query(user_text):
            p["needs_clarification"] = False
            p["clarification_question"] = ""

        meta = p.get("meta") or {}
        if not isinstance(meta, dict):
            meta = {}
        meta.setdefault("max_items", 12)
        meta.setdefault("required_terms", self._required_terms_from_text(user_text))
        p["meta"] = meta

        p.setdefault("category", None)
        p.setdefault("product_name", None)
        p.setdefault("postcode", None)
        p.setdefault("sku", None)
        p.setdefault("handoff_channel", None)
        p.setdefault("needs_clarification", False)
        p.setdefault("clarification_question", "")

        return p

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _execute_plan(self, plan: Dict[str, Any], user_text: str, session: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        facts: Dict[str, Any] = {}
        action = (plan.get("action") or "DO_NOTHING").strip().upper()
        intent = (plan.get("intent") or "unknown").strip().lower()
        meta = plan.get("meta") or {}

        category = plan.get("category")
        product_name = plan.get("product_name") or None

        raw_postcode = plan.get("postcode") or session.get("postcode")
        postcode = self._normalize_postcode(str(raw_postcode)) if raw_postcode else None

        if action == 'PRICE_CHECK' or intent == 'price_check':
            item = None
            sku = plan.get('sku')
            if self.catalog and isinstance(sku, str):
                item = self.catalog.get_item_by_sku(sku)
            if not item:
                item = self._exact_catalog_item_in_text(str(product_name or user_text))
            if isinstance(item, dict):
                facts['price'] = {key: item.get(key) for key in ('sku', 'name', 'price', 'unit', 'in_stock')}
                facts['currency'] = self._catalog_currency()
            return facts

        if action == 'FAQ_LOOKUP' or intent == 'faq':
            faq = self._find_faq(user_text, session, request_id=request_id)
            if faq:
                facts['faq'] = faq
            return facts

        if action == 'STORE_INFO' or intent == 'store_info':
            answer = self._store_info_answer(user_text) or self._delivery_information_answer(user_text)
            if answer:
                facts['store_info'] = {'answer': answer}
            return facts

        if action == "CHECK_DELIVERY" or intent == "check_delivery":
            if postcode:
                if self.policy:
                    date_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", user_text)
                    on_date = date_match.group(0) if date_match else None
                    try:
                        rule = self.policy.delivery_rule_for(postcode, on_date)
                        summary = self.policy.delivery_summary(postcode, on_date)
                    except Exception as e:
                        self._exc(request_id, "V7.delivery_failed", err=str(e))
                        rule, summary = None, ""
                    facts["delivery"] = {"postcode": postcode, "rule": rule, "summary": summary or "",
                                         "notes": self.policy.delivery_notes() or "",
                                         "notices": self.policy.service_notices(on_date, postcode)}
                else:
                    facts["delivery"] = {"postcode": postcode, "rule": None, "summary": ""}

                if self.geo:
                    try:
                        nb = self.geo.nearest_for_postcode(postcode)
                    except Exception as e:
                        self._exc(request_id, "V7.geo_failed", err=str(e))
                        nb = None
                    if nb:
                        facts.setdefault("branch", {})["nearest"] = nb

        if action == "SEARCH_PRODUCTS" or intent in {"search_product", "browse_category"}:
            query, tags = self._build_search_query(user_text, category, product_name, meta)
            try:
                limit = int((meta or {}).get("max_items") or 12)
            except Exception:
                limit = 12

            if meta.get("browse_all") and self.catalog:
                try:
                    items = self.catalog.list_all_items()[:limit]
                except Exception:
                    items = []
            else:
                items = self._catalog_search_safe(request_id, query=query, tags=tags, limit=limit)
            required = meta.get("required_terms") or self._required_terms_from_text(user_text)
            items = self._topic_enforce(items, required=required)
            items = self._post_filter_items(items, meta)
            facts["items"] = items
            facts["currency"] = self._catalog_currency()
            facts["search_meta"] = {
                "scope": meta.get("search_scope") or "top_picks",
                "item_level": bool(meta.get("item_level")),
                "max_items": limit,
                "wants_chunking": bool(meta.get("wants_chunking")),
            }

        return facts

    def _catalog_search_safe(self, request_id: str, query: str, tags: List[str], limit: int) -> List[Dict[str, Any]]:
        if not self.catalog:
            return []
        if not query and not tags:
            return []
        try:
            items = self.catalog.search(text=query, tags=tags, limit=limit) or []
            if not isinstance(items, list):
                return []
            return [it for it in items if isinstance(it, dict)]
        except Exception as e:
            self._exc(request_id, "V7.catalog.search_failed", err=str(e))
            return []

    def _catalog_has_match(self, token: str) -> bool:
        if not self.catalog:
            return False
        try:
            return bool(self.catalog.search(text=token, limit=1))
        except Exception:
            return False

    def _catalog_currency(self) -> str:
        if not self.catalog:
            return "GBP"
        try:
            return str(self.catalog.currency() or "GBP").upper()
        except Exception:
            return "GBP"

    def _topic_enforce(self, items: List[Dict[str, Any]], required: List[str]) -> List[Dict[str, Any]]:
        required = [str(x).strip().lower() for x in (required or []) if str(x).strip()]
        if not required:
            return items

        kept: List[Dict[str, Any]] = []
        for it in items or []:
            name = str(it.get("name") or it.get("title") or "").lower()
            tags = it.get("tags") or []
            tags_s = " ".join([str(x).lower() for x in tags])
            if any(r in name or r in tags_s for r in required):
                kept.append(it)

        return kept if kept else items

    def _post_filter_items(self, items: List[Dict[str, Any]], meta: Dict[str, Any]) -> List[Dict[str, Any]]:
        meta = meta or {}
        max_price = meta.get("max_price")
        sort = meta.get("sort")

        cleaned: List[Dict[str, Any]] = [it for it in (items or []) if isinstance(it, dict)]

        if isinstance(max_price, (int, float)):
            tmp: List[Dict[str, Any]] = []
            for it in cleaned:
                p = it.get("price")
                try:
                    p_val = float(p) if p is not None else None
                except Exception:
                    p_val = None
                if p_val is None or p_val <= float(max_price):
                    tmp.append(it)
            cleaned = tmp

        if sort in {"price_asc", "price_desc"}:
            def price_key(x: Dict[str, Any]) -> float:
                try:
                    return float(x.get("price"))
                except Exception:
                    return 10**12
            cleaned.sort(key=price_key, reverse=(sort == "price_desc"))

        return cleaned

    def _build_search_query(self, user_text: str, category: Optional[str], product_name: Optional[str], meta: Dict[str, Any]) -> Tuple[str, List[str]]:
        tags: List[str] = []
        query = ""

        meta = meta or {}
        meta_tags = meta.get("search_tags") or []
        if isinstance(meta_tags, str):
            meta_tags = [meta_tags]

        for t in meta_tags:
            t = str(t).strip().lower()
            if t and t not in tags:
                tags.append(t)

        if product_name:
            query = str(product_name).strip()
        elif category:
            query = str(category).strip().replace("_", " ")
        else:
            query = (user_text or "").strip()

        q_norm = self._normalize_text(query)
        if q_norm and len(q_norm.split()) <= 2:
            for x in q_norm.split():
                if x and x not in tags:
                    tags.append(x)

        if not category and not product_name and tags:
            query = " ".join(tags)

        query = self._normalize_text(query)
        return (query or "").strip(), tags

    # ------------------------------------------------------------------
    # Entities / UI
    # ------------------------------------------------------------------

    def _entities_from_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        entities: Dict[str, Any] = {}
        if plan.get("category"):
            entities["category"] = plan["category"]
        if plan.get("postcode"):
            pc = self._normalize_postcode(str(plan["postcode"])) or plan["postcode"]
            entities["postcode"] = pc
        if plan.get("sku"):
            entities["sku"] = plan["sku"]
        if plan.get("product_name"):
            entities["product_name"] = plan["product_name"]
        if plan.get("handoff_channel"):
            entities["handoff_channel"] = plan["handoff_channel"]
        return entities

    def _format_items_for_ui(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            out.append(
                {
                    "sku": it.get("sku") or it.get("id") or it.get("code"),
                    "name": it.get("name") or it.get("title"),
                    "price": it.get("price") or it.get("price_gbp") or it.get("amount"),
                    "unit": it.get("unit") or it.get("size") or "",
                    "in_stock": it.get("in_stock"),
                    "tags": it.get("tags") or [],
                    "category": it.get("category") or it.get("category_id"),
                    "url": it.get("url") or it.get("link"),
                    "image": it.get("image") or it.get("image_url"),
                    "raw": it,
                }
            )
        return out

    # ------------------------------------------------------------------
    # Text normalization
    # ------------------------------------------------------------------

    def _clean_text(self, text: str) -> str:
        t = (text or "").lower().strip()
        t = re.sub(r"[^a-z0-9\s$£€_-]+", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _normalize_text(self, text: str) -> str:
        t = self._clean_text(text)
        if not t:
            return t

        return t

    def _token_tags(self, text: str) -> List[str]:
        t = self._normalize_text(text)
        t = re.sub(r"[^a-z0-9\s_]+", " ", t)
        toks = [x.strip() for x in t.split() if x.strip()]
        out: List[str] = []
        for tok in toks:
            if tok not in out:
                out.append(tok)
        return out

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _info(self, rid: str, msg: str, **fields: Any) -> None:
        try:
            if self.logger:
                self.logger.info("%s | %s | %s", rid, msg, self._compact(fields))
            else:
                logger.info("%s | %s | %s", rid, msg, self._compact(fields))
        except Exception:
            pass

    def _debug(self, rid: str, msg: str, **fields: Any) -> None:
        try:
            if self.logger:
                self.logger.debug("%s | %s | %s", rid, msg, self._compact(fields))
            else:
                logger.debug("%s | %s | %s", rid, msg, self._compact(fields))
        except Exception:
            pass

    def _exc(self, rid: str, msg: str, **fields: Any) -> None:
        try:
            if self.logger:
                self.logger.exception("%s | %s | %s", rid, msg, self._compact(fields))
            else:
                logger.exception("%s | %s | %s", rid, msg, self._compact(fields))
        except Exception:
            pass

    @staticmethod
    def _compact(d: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, v in (d or {}).items():
            if v is None:
                continue
            if isinstance(v, str):
                out[k] = v if len(v) <= 400 else v[:400] + "…"
            elif isinstance(v, list):
                out[k] = v[:40]
            elif isinstance(v, dict):
                if len(v) > 25:
                    keys = list(v.keys())[:25]
                    out[k] = {kk: v.get(kk) for kk in keys}
                    out[k]["_truncated"] = True
                else:
                    out[k] = v
            else:
                out[k] = v
        return out

    @staticmethod
    def _clip(s: str, n: int) -> str:
        s = s or ""
        return s if len(s) <= n else s[:n] + "…"
