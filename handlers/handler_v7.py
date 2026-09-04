# handlers/handler_v7.py
from __future__ import annotations

import difflib
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from brain_v7 import BrainV7
from renderer_v7 import RendererV7
from service.validators import normalize_phone

logger = logging.getLogger("handler_v7")


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
    )

    _EXPLICIT_SHOPPING_WORDS = (
        "buy", "purchase", "price", "prices", "cost", "how much", "cheapest",
        "offer", "deal", "recommend", "list", "catalog", "catalogue", "available",
        "show", "browse", "view", "products", "items", "in stock", "do you have",
        "have you got", "do you sell", "looking for", "need", "want",
    )

    _SEARCH_STOP_WORDS = {
        "a", "an", "and", "any", "available", "buy", "catalog", "catalogue", "do",
        "for", "have", "i", "in", "is", "item", "items", "list", "looking", "me",
        "need", "of", "product", "products", "recommend", "show", "some", "the",
        "to", "want", "what", "with", "you", "your",
    }

    _BROWSE_ALL_PAT = re.compile(
        r"\b(show|browse|list|see|view)?\s*(all|full|entire|whole)?\s*"
        r"(products?|items?|catalog|catalogue|range)\b",
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
        r"\b(?:offers?|deals?|discounts?|promotions?|sales?|specials?)\b",
        re.I,
    )

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

        self.brain = BrainV7(getattr(deps, "openai_client", None))
        tone_style, max_sentences = self._tone_settings()
        self.renderer = RendererV7(
            getattr(deps, "rewriter", None),
            self.business_name,
            tone_style=tone_style,
            max_sentences=max_sentences,
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
            # 0) Greeting only
            if self._is_greeting(user_text):
                reply_text = (
                    f"Hi, I’m the {self._assistant_label()}. Tell me what you’re looking for and I’ll pull the right options.\n"
                    "You can ask about products, prices, delivery, or the nearest branch."
                )
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

            # 0.75) Out of scope
            if self._looks_out_of_scope(user_text):
                reply_text = (
                    f"I can only help with {self._business_label()} products, prices, delivery, and branch details."
                )
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

            # 0.9) Explicit human handoff and voluntary contact details.
            contact = self._handoff_contact(user_text, session_snapshot)
            if contact and self._has_pending_handoff(session_snapshot):
                plan = self._simple_plan("handoff_contact_captured", "HUMAN_HANDOFF", session_snapshot)
                reply_text = (
                    "Thanks, I’ve recorded those contact details for the team. "
                    "You can add any product or delivery details that would help them."
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

            if self._requests_handoff(user_text):
                plan = self._simple_plan("human_handoff", "HUMAN_HANDOFF", session_snapshot)
                reply_text = (
                    "I can have the team follow up. Please send a phone number or email, "
                    "plus a short note about what you need."
                )
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

            store_info = self._store_info_answer(user_text)
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
            product_query = self._looks_like_product_query(user_text)
            faq = self._find_faq(user_text, session_snapshot, request_id=request_id)
            if faq and not (product_query and self._is_explicit_shopping_request(user_text)):
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

            if product_query:
                plan = self._heuristic_plan(user_text, request_id=request_id)

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
            if intent_norm == "unknown" and not self._looks_like_product_query(user_text):
                reply_text = "Tell me what you need: a product, price, delivery, or branch information."
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

            # 7) Execute
            facts = self._execute_plan(plan, user_text, session_snapshot, request_id=request_id)

            # 8) Retry if empty search
            if (plan.get("action") or "").strip().upper() == "SEARCH_PRODUCTS":
                if not (facts.get("items") or []):
                    retry = self._retry_search_if_worth_it(plan, user_text=user_text, request_id=request_id)
                    if retry is not None:
                        facts["items"] = retry

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
            return (
                f"Yes — I’m an AI-powered {self._assistant_label()}. "
                "I can help with products, prices, delivery, and nearest branch details."
            )

        if "help" in t:
            return "Sure — tell me what you need. I can help you browse products, compare prices, check delivery, or find a branch."

        if any(x in t for x in ("how are you", "how r u", "hru", "whats up", "what's up")):
            return "I’m ready to help. Ask me about products, prices, delivery, or nearest branch."

        return f"I’m the {self._assistant_label()}. Ask me about products, prices, delivery, or the nearest branch."

    def _business_label(self) -> str:
        return self.business_name or "this business"

    def _assistant_label(self) -> str:
        if self.business_name:
            return f"{self.business_name} sales assistant"
        return "sales assistant for this business"

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
        for h in self._OUT_OF_SCOPE_HINTS:
            if h in t:
                if self._looks_like_product_query(text):
                    return False
                return True
        return False

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

        for s in self._SMALLTALK:
            if s in t:
                return True

        if ("ai" in t or "bot" in t or "real" in t) and any(w in t for w in ("where", "were", "what", "is", "are", "you")):
            return True

        return False

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
        text = self._clean_text(user_text)
        return any(phrase in text for phrase in self._HANDOFF_PHRASES)

    def _store_info_answer(self, user_text: str) -> Optional[str]:
        text = self._clean_text(user_text)
        if not text:
            return None

        is_contact_question = (
            any(phrase in text for phrase in self._STORE_INFO_PHRASES)
            or bool(re.search(r"\b(contact|phone|telephone|email|website)\b", text))
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

    def _current_offers(self, user_text: str) -> Optional[Dict[str, Any]]:
        """Return only current tenant offers, optionally scoped to a named product."""
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
    ) -> Dict[str, Any]:
        dt_ms = int((time.perf_counter() - t0) * 1000)
        ui = {
            "has_catalog": bool(items),
            "catalog_items": self._format_items_for_ui(items or []),
        }
        return {
            "reply": reply,
            "mode": "v7",
            "intent": intent or "unknown",
            "entities": entities or {},
            "facts": facts or {},
            "ui": ui,
            "meta": {"request_id": request_id, "latency_ms": dt_ms},
        }

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
            hints: Dict[str, Any] = {}
            if self.synonyms:
                hints["synonyms"] = self.synonyms
            if self.catalog:
                hints["categories"] = self.catalog.categories()

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

        if (category or product_name) and action in {"", "DO_NOTHING", "STORE_INFO", "FAQ_LOOKUP"}:
            p["action"] = "SEARCH_PRODUCTS"
            if (p.get("intent") or "").strip().lower() in {"", "unknown"}:
                p["intent"] = "browse_category" if category and not product_name else "search_product"

        if p.get("needs_clarification") and self._looks_like_product_query(user_text):
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

        if action == "CHECK_DELIVERY" or intent == "check_delivery":
            if postcode:
                if self.policy:
                    try:
                        rule = self.policy.delivery_rule_for(postcode)
                        summary = self.policy.delivery_summary(postcode)
                    except Exception as e:
                        self._exc(request_id, "V7.delivery_failed", err=str(e))
                        rule, summary = None, ""
                    facts["delivery"] = {"postcode": postcode, "rule": rule, "summary": summary or ""}
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
