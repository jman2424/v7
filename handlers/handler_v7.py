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

logger = logging.getLogger("handler_v7")


class MessageHandlerV7:
    """
    V7 handler (crash-proof + smarter routing)

    Fixes in this remake:
    - Stop treating ANY short message (<=7 words) as a product query
      (this was the reason “is this ai” got forced into product search).
    - Respect Brain smalltalk/greeting outcomes (don’t force SEARCH_PRODUCTS).
    - Stronger item/cut handling: “fillets”, “wings”, “mince”, etc can search without category.
    - If a product-ish query returns zero items, do ONE safe retry search with a simplified query
      (prevents menu-fallback when the catalog would match a simpler query).
    - Delivery/nearest-branch logic kept (postcode in message or session, else ask).
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
    }

    _MEATS = ("chicken", "beef", "lamb", "goat")

    # “cut/topic” words that usually mean product search
    _TOPIC_WORDS = (
        "steak", "chops", "wings", "wing", "mince", "kofta", "breast", "thigh", "drumsticks",
        "ribs", "rib", "fillet", "fillets", "sirloin", "ribeye", "rump", "leg", "shoulder",
        "neck", "shank", "burger", "burgers", "patties", "liver", "kidney", "kidneys",
        "paya", "feet", "nuggets", "kebab", "kebabs"
    )

    # Words that imply “I want products” even if not a cut
    _BUY_WORDS = (
        "price", "prices", "cost", "how much", "cheapest", "cheap", "offer", "deal",
        "recommend", "recommendation", "suggest", "suggestion", "options", "list", "full list",
        "family pack", "bbq", "barbecue", "grill", "grilling", "curry"
    )

    _MEAT_ALIASES = {
        "poultry": "chicken",
        "hen": "chicken",
        "mutton": "lamb",
        "cow": "beef",
    }

    # ---- Postcode regexes (pragmatic UK-ish) ----
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

    def __init__(self, deps: Any):
        self.catalog = getattr(deps, "catalog", None)
        self.policy = getattr(deps, "policy", None)  # delivery_rule_for, delivery_summary
        self.geo = getattr(deps, "geo", None)        # nearest_for_postcode
        self.faq = getattr(deps, "faq", None)
        self.synonyms = getattr(deps, "synonyms", None)

        # Optional structured logger from deps; if absent, use module logger
        self.logger = getattr(deps, "logger", None)

        self.brain = BrainV7(getattr(deps, "openai_client", None))
        self.renderer = RendererV7(getattr(deps, "rewriter", None))

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

        self._info(
            request_id,
            "V7.start",
            tenant=tenant,
            session=session_id,
            channel=channel,
            text=self._clip(user_text, 240),
            sess=session_snapshot,
        )

        try:
            # 0) Greeting / small talk (pure)
            if self._is_greeting_or_smalltalk(user_text):
                reply_text = (
                    "Salam! 👋 Tell me what you’re after and I’ll pull options.\n"
                    "Examples: chicken wings • lamb chops • beef steak • cheapest lamb • delivery to E1 6AN"
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

            # 1) Branch/delivery questions: do NOT fall into product pipeline
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
                self._info(request_id, "V7.branch_delivery_intent", postcode=str(pc))

                facts = self._execute_plan(plan, user_text, session_snapshot, request_id=request_id)
                entities = self._entities_from_plan(plan)

                reply_text = self.renderer.render(
                    user_text=user_text,
                    plan=plan,
                    facts=facts,
                    session=session_snapshot,
                )

                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="check_delivery",
                    plan=plan,
                    facts=facts,
                    entities=entities,
                    items=facts.get("items") or [],
                )

            # 2) Postcode-only (force delivery)
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
                self._info(request_id, "V7.force_delivery_from_postcode", postcode=extracted_pc)

                facts = self._execute_plan(plan, user_text, session_snapshot, request_id=request_id)
                entities = self._entities_from_plan(plan)

                reply_text = self.renderer.render(
                    user_text=user_text,
                    plan=plan,
                    facts=facts,
                    session=session_snapshot,
                )

                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent=plan.get("intent") or "check_delivery",
                    plan=plan,
                    facts=facts,
                    entities=entities,
                    items=facts.get("items") or [],
                )

            # 3) Multi-meat join
            multi = self._multi_query_plan(user_text, request_id=request_id)
            if multi:
                plan = multi["plan"]
                facts = multi["facts"]
                entities = self._entities_from_plan(plan)

                reply_text = self.renderer.render(
                    user_text=user_text,
                    plan=plan,
                    facts=facts,
                    session=session_snapshot,
                )

                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent=plan.get("intent"),
                    plan=plan,
                    facts=facts,
                    entities=entities,
                    items=facts.get("items") or [],
                )

            # 4) Heuristic plan (only when truly product-ish)
            plan = None
            if self._looks_like_product_query(user_text):
                plan = self._heuristic_plan(user_text, request_id=request_id)
                if plan:
                    self._info(request_id, "V7.heuristic_used", plan=self._safe_plan_log(plan))

            # 5) Brain plan
            if not plan:
                plan = self._safe_plan(user_text=user_text, session=session_snapshot, request_id=request_id)
                self._debug(request_id, "V7.plan_raw", plan=self._safe_plan_log(plan))

                plan = self._normalize_plan(plan, user_text=user_text)
                self._debug(request_id, "V7.plan_norm", plan=self._safe_plan_log(plan))

            # 6) If Brain says smalltalk/unknown AND input is not product-ish, DO NOT force search.
            intent_norm = (plan.get("intent") or "unknown").strip().lower()
            action_norm = (plan.get("action") or "").strip().upper()

            if intent_norm in {"smalltalk", "greeting"} or action_norm in {"SMALLTALK_REPLY", "GREET"}:
                facts = {}
                entities = self._entities_from_plan(plan)
                reply_text = self.renderer.render(user_text=user_text, plan=plan, facts=facts, session=session_snapshot)
                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent=plan.get("intent"),
                    plan=plan,
                    facts=facts,
                    entities=entities,
                    items=[],
                )

            if intent_norm in {"unknown"} and (not self._looks_like_product_query(user_text)):
                # Keep it conversational instead of forcing catalog search
                safe_plan = {
                    "intent": "smalltalk",
                    "action": "SMALLTALK_REPLY",
                    "category": None,
                    "product_name": None,
                    "postcode": session_snapshot.get("postcode"),
                    "sku": session_snapshot.get("last_sku"),
                    "handoff_channel": None,
                    "needs_clarification": False,
                    "clarification_question": "",
                    "meta": {"max_items": 0},
                }
                facts = {}
                entities = self._entities_from_plan(safe_plan)
                reply_text = self.renderer.render(user_text=user_text, plan=safe_plan, facts=facts, session=session_snapshot)
                return self._wrap_reply(
                    request_id=request_id,
                    t0=t0,
                    reply=reply_text,
                    intent="smalltalk",
                    plan=safe_plan,
                    facts=facts,
                    entities=entities,
                    items=[],
                )

            # 7) Execute plan
            facts = self._execute_plan(plan, user_text, session_snapshot, request_id=request_id)

            # 8) If it was product search and came back empty, do ONE retry with a simplified query
            if (plan.get("action") or "").strip().upper() == "SEARCH_PRODUCTS":
                items0 = facts.get("items") or []
                if not items0:
                    retry = self._retry_search_if_worth_it(plan, user_text=user_text, request_id=request_id)
                    if retry is not None:
                        facts["items"] = retry

            # 9) Entities
            entities = self._entities_from_plan(plan)

            # 10) Render
            reply_text = self.renderer.render(
                user_text=user_text,
                plan=plan,
                facts=facts,
                session=session_snapshot,
            )

            return self._wrap_reply(
                request_id=request_id,
                t0=t0,
                reply=reply_text,
                intent=plan.get("intent"),
                plan=plan,
                facts=facts,
                entities=entities,
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
    # RETRY SEARCH (prevents “menu fallback” when query was too narrow)
    # ------------------------------------------------------------------

    def _retry_search_if_worth_it(self, plan: Dict[str, Any], *, user_text: str, request_id: str) -> Optional[List[Dict[str, Any]]]:
        if not self.catalog:
            return None

        meta = plan.get("meta") or {}
        q = (plan.get("product_name") or user_text or "").strip()
        q_clean = self._normalize_text(q)

        # Only retry when query is short or a single cut word
        tokens = [t for t in q_clean.split() if t]
        if not tokens or len(tokens) > 3:
            return None

        # Try the strongest “cut” token as both query + tag
        cut = None
        for t in tokens:
            if t in set(self._TOPIC_WORDS):
                cut = t
                break

        if not cut:
            return None

        try:
            limit = int(meta.get("max_items") or 12)
        except Exception:
            limit = 12

        tags = self._token_tags(cut)
        self._info(request_id, "V7.catalog.retry", cut=cut, tags=tags, limit=limit)

        items = self._catalog_search_safe(request_id, query=cut, tags=tags, limit=limit)
        return items

    # ------------------------------------------------------------------
    # BRANCH / DELIVERY INTENT DETECTION
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # RESPONSE WRAPPER
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

    # ------------------------------------------------------------------
    # REQUEST ID
    # ------------------------------------------------------------------

    def _get_request_id(self, ctx: Any) -> Optional[str]:
        try:
            md = getattr(ctx, "metadata", None) or {}
            if isinstance(md, dict):
                return md.get("rid") or md.get("request_id")
        except Exception:
            return None
        return None

    # ------------------------------------------------------------------
    # POSTCODE (EXTRACT + NORMALIZE)
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
    # GREETING / SMALL TALK
    # ------------------------------------------------------------------

    def _is_greeting_or_smalltalk(self, text: str) -> bool:
        t = self._clean_text(text)
        if not t:
            return False

        for s in self._SMALLTALK:
            if s in t:
                return True

        if t in self._GREETINGS:
            return True
        for g in self._GREETINGS:
            if t.startswith(g + " "):
                return True

        gmatch = difflib.get_close_matches(t, list(self._GREETINGS), n=1, cutoff=0.82)
        return bool(gmatch)

    # ------------------------------------------------------------------
    # MULTI-MEAT JOIN
    # ------------------------------------------------------------------

    def _multi_query_plan(self, user_text: str, request_id: str) -> Optional[Dict[str, Any]]:
        if not self.catalog:
            return None

        text = self._normalize_text(user_text)
        if not text:
            return None

        meats = self._extract_meats(text)
        if len(meats) < 2:
            return None

        mods = self._parse_modifiers(text)
        topic = self._extract_topic(text)

        per_meat_limit = 8
        total_limit = 18

        merged: List[Dict[str, Any]] = []
        seen: set = set()
        groups: Dict[str, List[Dict[str, Any]]] = {}

        for meat in meats:
            query = f"{meat} {topic}".strip()
            tags = self._token_tags(query)
            for x in mods.get("tags") or []:
                if x not in tags:
                    tags.append(x)

            self._info(request_id, "V7.multi.search", meat=meat, query=self._clip(query, 120), tags=tags[:20])

            items = self._catalog_search_safe(request_id, query=query, tags=tags, limit=per_meat_limit)
            items = self._topic_enforce(items, required=self._required_terms_from_text(topic))
            items = self._post_filter_items(items, {"max_price": mods.get("max_price"), "sort": mods.get("sort")})

            groups[meat] = items

            for it in items:
                if not isinstance(it, dict):
                    continue
                key = (it.get("sku") or it.get("id") or it.get("code") or it.get("name") or "").strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(it)

        merged = self._post_filter_items(merged, {"max_price": mods.get("max_price"), "sort": mods.get("sort")})
        merged = merged[:total_limit]

        plan = {
            "intent": "search_product",
            "action": "SEARCH_PRODUCTS",
            "category": None,
            "product_name": text,
            "postcode": None,
            "sku": None,
            "handoff_channel": None,
            "needs_clarification": False,
            "clarification_question": "",
            "meta": {
                "max_items": total_limit,
                "search_tags": self._token_tags(text),
                "sort": mods.get("sort"),
                "max_price": mods.get("max_price"),
                "required_terms": self._required_terms_from_text(topic),
                "multi_meats": meats,
                "topic": topic,
            },
        }

        facts = {"items": merged, "groups": groups, "multi_meats": meats, "topic": topic}
        self._info(request_id, "V7.multi.merged", meats=meats, topic=topic, count=len(merged))
        return {"plan": plan, "facts": facts}

    def _extract_meats(self, text: str) -> List[str]:
        t = self._clean_text(text)

        for k, v in self._MEAT_ALIASES.items():
            t = re.sub(rf"\b{re.escape(k)}\b", v, t)

        found: List[str] = []
        for meat in self._MEATS:
            if re.search(rf"\b{re.escape(meat)}\b", t):
                found.append(meat)

        for target in ("chicken", "lamb", "beef"):
            if target not in found:
                for tok in t.split():
                    if difflib.get_close_matches(tok, [target], n=1, cutoff=0.78):
                        found.append(target)
                        break

        out: List[str] = []
        for x in found:
            if x not in out:
                out.append(x)
        return out

    def _extract_topic(self, text: str) -> str:
        t = self._clean_text(text)
        t = self._strip_modifier_words(t)
        t = re.sub(r"\b(and|or|with|plus)\b", " ", t)
        for meat in self._MEATS:
            t = re.sub(rf"\b{re.escape(meat)}\b", " ", t)
        t = re.sub(r"\s+", " ", t).strip()

        present = self._required_terms_from_text(t)
        if present:
            return " ".join(present)
        return t or "all"

    # ------------------------------------------------------------------
    # HEURISTICS (IMPORTANT FIX: stop “<=7 words => product query”)
    # ------------------------------------------------------------------

    def _looks_like_product_query(self, user_text: str) -> bool:
        t = self._clean_text(user_text)
        if not t:
            return False

        # If it contains a clear signal, it’s product-y
        if any(re.search(rf"\b{re.escape(w)}\b", t) for w in self._MEATS):
            return True
        if any(re.search(rf"\b{re.escape(w)}\b", t) for w in self._TOPIC_WORDS):
            return True
        if any(w in t for w in self._BUY_WORDS):
            return True
        if "£" in user_text or re.search(r"\b(under|below|less than)\b", t):
            return True

        # If it’s basically a noun-like single token (but NOT obvious smalltalk)
        toks = t.split()
        if len(toks) == 1:
            if toks[0] in {"ai", "bot", "hello", "hi", "hey", "salam"}:
                return False
            # single token like "fillets" or "wings" should already have matched _TOPIC_WORDS above
            return toks[0] in set(self._TOPIC_WORDS)

        return False

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

        tags: List[str] = []
        if re.search(r"\b(bbq|barbecue)\b", t):
            tags.append("bbq")
        if re.search(r"\b(marinated|marinaded|marinted)\b", t):
            tags.append("marinated")
        if re.search(r"\bboneless\b", t):
            tags.append("boneless")

        return {"sort": sort, "max_price": max_price, "tags": tags}

    def _required_terms_from_text(self, text: str) -> List[str]:
        t = self._clean_text(text)
        if not t:
            return []
        out: List[str] = []
        for w in self._TOPIC_WORDS:
            if re.search(rf"\b{re.escape(w)}\b", t):
                out.append(w)
        return out

    def _strip_modifier_words(self, text: str) -> str:
        s = self._clean_text(text)
        s = re.sub(
            r"\b(cheapest|chepest|cheap|lowest|low|most|expensive|highest|premium|best|"
            r"under|below|less|than|boneless|bbq|barbecue|marinated|marinted)\b",
            " ",
            s,
        )
        s = s.replace("£", " ")
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _heuristic_plan(self, user_text: str, request_id: str) -> Optional[Dict[str, Any]]:
        t = self._normalize_text(user_text)
        if not t:
            return None

        mods = self._parse_modifiers(t)
        required = self._required_terms_from_text(t)

        core = self._strip_modifier_words(t) or t
        core = self._normalize_text(core)

        cat = self._fuzzy_category_match(core, request_id=request_id)

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
        }

        if cat:
            return {
                "intent": "browse_category",
                "action": "SEARCH_PRODUCTS",
                "category": cat,
                "product_name": None,
                "postcode": None,
                "sku": None,
                "handoff_channel": None,
                "needs_clarification": False,
                "clarification_question": "",
                "meta": meta,
            }

        return {
            "intent": "search_product",
            "action": "SEARCH_PRODUCTS",
            "category": None,
            "product_name": core,
            "postcode": None,
            "sku": None,
            "handoff_channel": None,
            "needs_clarification": False,
            "clarification_question": "",
            "meta": meta,
        }

    def _fuzzy_category_match(self, text: str, request_id: str) -> Optional[str]:
        if not self.catalog:
            return None
        try:
            cats = self.catalog.categories() or []
        except Exception as e:
            self._exc(request_id, "V7.categories_failed", err=str(e))
            return None

        candidates: List[str] = []
        id_map: Dict[str, str] = {}

        for c in cats:
            if not isinstance(c, dict):
                continue
            cid = (c.get("id") or "").strip()
            nm = (c.get("name") or "").strip()
            if cid:
                k = cid.lower()
                candidates.append(k)
                id_map[k] = cid
            if nm:
                k = nm.lower()
                candidates.append(k)
                id_map[k] = cid or nm

        if not candidates:
            return None

        text_l = self._clean_text(text)
        if text_l in id_map:
            return id_map[text_l]

        match = difflib.get_close_matches(text_l, candidates, n=1, cutoff=0.78)
        if match:
            return id_map.get(match[0]) or match[0]
        return None

    # ------------------------------------------------------------------
    # BRAIN WRAPPER + NORMALIZER
    # ------------------------------------------------------------------

    def _safe_plan(self, user_text: str, session: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        try:
            hints: Dict[str, Any] = {}

            if self.catalog:
                try:
                    cats = self.catalog.categories()
                    hints["categories"] = [
                        {"id": c.get("id"), "name": c.get("name")}
                        for c in (cats or [])
                        if isinstance(c, dict) and c.get("id") and c.get("name")
                    ]
                except Exception as e:
                    self._exc(request_id, "V7.hints_categories_failed", err=str(e))

            if self.synonyms:
                hints["synonyms"] = self.synonyms

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

        # Don’t auto-cancel a real clarification from the brain if the text is short;
        # brain might need a slot. Only cancel if text is clearly a cut/product term.
        if p.get("needs_clarification"):
            if self._looks_like_product_query(user_text):
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
    # EXECUTION
    # ------------------------------------------------------------------

    def _execute_plan(
        self,
        plan: Dict[str, Any],
        user_text: str,
        session: Dict[str, Any],
        request_id: str,
    ) -> Dict[str, Any]:
        facts: Dict[str, Any] = {}

        action = (plan.get("action") or "DO_NOTHING").strip().upper()
        intent = (plan.get("intent") or "unknown").strip().lower()
        meta = plan.get("meta") or {}

        category = plan.get("category")
        product_name = plan.get("product_name") or None

        raw_postcode = plan.get("postcode") or session.get("postcode")
        postcode = self._normalize_postcode(str(raw_postcode)) if raw_postcode else None

        sku = plan.get("sku")

        # DELIVERY
        if action == "CHECK_DELIVERY" or intent == "check_delivery":
            if postcode:
                self._info(
                    request_id,
                    "V7.delivery.deps",
                    has_policy=bool(self.policy),
                    has_geo=bool(self.geo),
                    postcode=postcode,
                )

                if self.policy:
                    try:
                        rule = self.policy.delivery_rule_for(postcode)
                        summary = self.policy.delivery_summary(postcode)
                        self._info(request_id, "V7.delivery.ok", has_rule=bool(rule), summary_len=len(summary or ""))
                    except Exception as e:
                        self._exc(request_id, "V7.delivery_failed", err=str(e))
                        rule, summary = None, ""
                    facts["delivery"] = {"postcode": postcode, "rule": rule, "summary": summary or ""}
                else:
                    facts["delivery"] = {"postcode": postcode, "rule": None, "summary": ""}

                if self.geo:
                    try:
                        nb = self.geo.nearest_for_postcode(postcode)
                        self._info(
                            request_id,
                            "V7.geo.ok",
                            has_nearest=bool(nb),
                            nearest_id=(nb or {}).get("id") if isinstance(nb, dict) else None,
                        )
                    except Exception as e:
                        self._exc(request_id, "V7.geo_failed", err=str(e))
                        nb = None
                    if nb:
                        facts.setdefault("branch", {})["nearest"] = nb

        # PRODUCTS
        if action == "SEARCH_PRODUCTS" or intent in {"search_product", "browse_category"}:
            query, tags = self._build_search_query(user_text, category, product_name, meta)

            try:
                limit = int((meta or {}).get("max_items") or 12)
            except Exception:
                limit = 12

            self._info(request_id, "V7.catalog.search", query=self._clip(query, 120), tags=(tags or [])[:20], limit=limit)

            items = self._catalog_search_safe(request_id, query=query, tags=tags, limit=limit)

            required = meta.get("required_terms") or self._required_terms_from_text(user_text)
            items = self._topic_enforce(items, required=required)
            items = self._post_filter_items(items, meta)

            facts["items"] = items
            self._debug(request_id, "V7.catalog.result", count=len(items or []), preview=self._preview_items(items))

        # PRICE CHECK
        if action == "PRICE_CHECK" or intent == "price_check":
            if self.catalog and sku:
                try:
                    price_val = self.catalog.price_of(sku)
                    in_stock = self.catalog.in_stock(sku)
                    try:
                        meta_info = self.catalog.meta_of(sku)
                    except Exception:
                        meta_info = {}
                except Exception as e:
                    self._exc(request_id, "V7.price_failed", err=str(e))
                    price_val, in_stock, meta_info = None, None, {}
                facts["price"] = {
                    "sku": sku,
                    "price": price_val,
                    "in_stock": in_stock,
                    "name": meta_info.get("name"),
                    "unit": meta_info.get("unit"),
                }

        # FAQ / STORE INFO
        if action in {"STORE_INFO", "FAQ_LOOKUP"} or intent in {"store_info", "faq"}:
            if self.faq:
                try:
                    m = self.faq.best_match(user_text, hint_tags=None, top_k=1)
                except Exception as e:
                    self._exc(request_id, "V7.faq_best_match_failed", err=str(e))
                    m = None

                if m:
                    entry = m[0]
                    placeholders: Dict[str, Any] = {}
                    if postcode and self.policy:
                        placeholders["postcode"] = postcode
                        try:
                            placeholders["delivery_summary"] = self.policy.delivery_summary(postcode) or ""
                        except Exception:
                            placeholders["delivery_summary"] = ""

                    try:
                        answer = self.faq.render_answer(entry, placeholders)
                    except Exception as e:
                        self._exc(request_id, "V7.faq_render_failed", err=str(e))
                        answer = ""

                    facts["faq"] = {"entry": entry, "answer": answer}

        return facts

    def _catalog_search_safe(self, request_id: str, query: str, tags: List[str], limit: int) -> List[Dict[str, Any]]:
        if not self.catalog:
            self._debug(request_id, "V7.catalog_missing")
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

    def _topic_enforce(self, items: List[Dict[str, Any]], required: List[str]) -> List[Dict[str, Any]]:
        required = [str(x).strip().lower() for x in (required or []) if str(x).strip()]
        if not required:
            return items

        kept: List[Dict[str, Any]] = []
        for it in items or []:
            name = str(it.get("name") or it.get("title") or "").lower()
            tags = it.get("tags") or []
            tags_s = " ".join([str(x).lower() for x in tags])

            ok = False
            for r in required:
                if r in name or r in tags_s:
                    ok = True
                    break
            if ok:
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

    def _build_search_query(
        self,
        user_text: str,
        category: Optional[str],
        product_name: Optional[str],
        meta: Dict[str, Any],
    ) -> Tuple[str, List[str]]:
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
            cat_key = str(category).strip().lower()
            query = cat_key.replace("_", " ")
            if cat_key and cat_key not in tags:
                tags.append(cat_key)
            for token in re.split(r"[ _]+", cat_key):
                if token and token not in tags:
                    tags.append(token)
        else:
            query = (user_text or "").strip()

        # If it’s a cut-only query like “fillets”, make sure it’s in tags too
        q_norm = self._normalize_text(query)
        if q_norm and q_norm not in tags and len(q_norm.split()) <= 2:
            tags.extend([x for x in q_norm.split() if x and x not in tags])

        if not category and not product_name and tags:
            query = " ".join(tags)

        query = self._normalize_text(query)
        return (query or "").strip(), tags

    # ------------------------------------------------------------------
    # ENTITIES + UI
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
            sku = it.get("sku") or it.get("id") or it.get("code")
            name = it.get("name") or it.get("title")
            price = it.get("price") or it.get("price_gbp") or it.get("amount")
            unit = it.get("unit") or it.get("size") or ""
            in_stock = it.get("in_stock")
            if in_stock is None:
                stock_val = it.get("stock", None)
                if isinstance(stock_val, int):
                    in_stock = stock_val > 0
            out.append(
                {
                    "sku": sku,
                    "name": name,
                    "price": price,
                    "unit": unit,
                    "in_stock": in_stock,
                    "tags": it.get("tags") or [],
                    "category": it.get("category") or it.get("category_id"),
                    "url": it.get("url") or it.get("link"),
                    "image": it.get("image") or it.get("image_url"),
                    "raw": it,
                }
            )
        return out

    # ------------------------------------------------------------------
    # TEXT NORMALIZATION
    # ------------------------------------------------------------------

    def _clean_text(self, text: str) -> str:
        t = (text or "").lower().strip()
        t = re.sub(r"[^a-z0-9\s£_-]+", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _normalize_text(self, text: str) -> str:
        t = self._clean_text(text)
        if not t:
            return t

        toks = t.split()
        out: List[str] = []
        for tok in toks:
            if tok in self._MEAT_ALIASES:
                out.append(self._MEAT_ALIASES[tok])
                continue
            out.append(self._fuzzy_fix_meat_token(tok))
        return " ".join(out).strip()

    def _fuzzy_fix_meat_token(self, tok: str) -> str:
        tok = (tok or "").lower().strip()
        if not tok:
            return tok
        if tok in self._MEATS:
            return tok
        m = difflib.get_close_matches(tok, list(self._MEATS), n=1, cutoff=0.78)
        return m[0] if m else tok

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
    # LOGGING (never crash)
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

    def _safe_plan_log(self, plan: Any) -> Dict[str, Any]:
        if not isinstance(plan, dict):
            return {"_type": str(type(plan))}
        keep = (
            "intent",
            "action",
            "category",
            "product_name",
            "postcode",
            "sku",
            "needs_clarification",
            "clarification_question",
            "meta",
        )
        out: Dict[str, Any] = {}
        for k in keep:
            if k in plan:
                val = plan.get(k)
                if k == "clarification_question":
                    val = self._clip(str(val or ""), 160)
                if k == "product_name":
                    val = self._clip(str(val or ""), 120)
                out[k] = val
        return out

    @staticmethod
    def _preview_items(items: Any, n: int = 3) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not isinstance(items, list):
            return out
        for it in items[:n]:
            if not isinstance(it, dict):
                continue
            out.append(
                {
                    "sku": it.get("sku") or it.get("id") or it.get("code"),
                    "name": it.get("name") or it.get("title"),
                    "price": it.get("price") or it.get("price_gbp") or it.get("amount"),
                }
            )
        return out
