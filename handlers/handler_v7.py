# handlers/handler_v7.py
from __future__ import annotations

import difflib
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from brain_v7 import BrainV7
from renderer_v7 import RendererV7

# ✅ NEW: use your existing validator
from service.validators import normalize_postcode


class MessageHandlerV7:
    """
    V7 handler (crash-proof + smarter guidance, minimal hardcoding)

    Patch (Feb 2026):
    - If user sends a postcode (e.g. "E7 9QS" or "E79QS"), force CHECK_DELIVERY.
    - Prevent postcodes being mis-classed as product queries.
    """

    _GREETINGS = {
        "hello", "hi", "hey", "hiya", "yo", "sup",
        "asalam", "assalam", "salam", "asalaam", "salaam",
        "good morning", "good afternoon", "good evening",
    }

    _SMALLTALK = {
        "how are you", "how r u", "hru", "whats up", "what's up",
        "help", "can you help", "can u help", "need help",
    }

    _MEATS = ("chicken", "beef", "lamb", "goat")

    _TOPIC_WORDS = (
        "steak", "chops", "wings", "mince", "kofta", "breast", "thigh", "drumsticks", "ribs",
        "fillet", "sirloin", "ribeye", "rump", "leg", "shoulder", "neck", "shank", "burger", "patties"
    )

    _MEAT_ALIASES = {
        "poultry": "chicken",
        "hen": "chicken",
        "mutton": "lamb",
        "cow": "beef",
    }

    # ✅ NEW: delivery language signals
    _DELIVERY_WORDS = (
        "delivery", "deliver", "delivering", "ship", "shipping",
        "nearest", "closest", "near me", "store", "shop", "branch",
        "address", "postcode", "post code"
    )

    def __init__(self, deps: Any):
        self.catalog = getattr(deps, "catalog", None)
        self.policy = getattr(deps, "policy", None)
        self.geo = getattr(deps, "geo", None)
        self.faq = getattr(deps, "faq", None)
        self.synonyms = getattr(deps, "synonyms", None)
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
            # 0) Greeting / small-talk fast lane
            if self._is_greeting_or_smalltalk(user_text):
                reply_text = (
                    "Salam! 👋 Tell me what you’re after and I’ll pull options.\n"
                    "Examples: chicken wings • lamb chops • beef steak • cheapest lamb • delivery to E1 6AN"
                )
                dt_ms = int((time.perf_counter() - t0) * 1000)
                return {
                    "reply": reply_text,
                    "mode": "v7",
                    "intent": "greeting",
                    "entities": {},
                    "facts": {},
                    "ui": {"has_catalog": False, "catalog_items": []},
                    "meta": {"request_id": request_id, "latency_ms": dt_ms},
                }

            # ✅ 0.5) POSTCODE FAST LANE (THIS IS THE KEY FIX)
            # If input is a postcode OR contains a postcode with delivery/store language,
            # force CHECK_DELIVERY so it never falls into product-search.
            pc = self._extract_postcode(user_text)
            if pc and (self._is_postcode_only(user_text, pc) or self._has_delivery_words(user_text)):
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
                self._info(request_id, "V7.postcode_fastlane", postcode=pc)

                facts = self._execute_plan(plan, user_text, session_snapshot, request_id=request_id)
                entities = self._entities_from_plan(plan)

                reply_text = self.renderer.render(
                    user_text=user_text,
                    plan=plan,
                    facts=facts,
                    session=session_snapshot,
                )

                dt_ms = int((time.perf_counter() - t0) * 1000)
                return {
                    "reply": reply_text,
                    "mode": "v7",
                    "intent": plan.get("intent"),
                    "entities": entities,
                    "facts": facts,
                    "ui": {"has_catalog": False, "catalog_items": []},
                    "meta": {"request_id": request_id, "latency_ms": dt_ms},
                }

            # 1) Multi-meat join first
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

                ui = {
                    "has_catalog": bool(facts.get("items")),
                    "catalog_items": self._format_items_for_ui(facts.get("items") or []),
                }

                dt_ms = int((time.perf_counter() - t0) * 1000)
                self._info(request_id, "V7.ok_multi", items_count=len(facts.get("items") or []), latency_ms=dt_ms)

                return {
                    "reply": reply_text,
                    "mode": "v7",
                    "intent": plan.get("intent"),
                    "entities": entities,
                    "facts": facts,
                    "ui": ui,
                    "meta": {"request_id": request_id, "latency_ms": dt_ms},
                }

            # 2) Heuristic plan
            plan = self._heuristic_plan(user_text, request_id=request_id)
            if plan:
                self._info(request_id, "V7.heuristic_used", plan=self._safe_plan_log(plan))
            else:
                # 3) Brain plan
                plan = self._safe_plan(user_text=user_text, session=session_snapshot, request_id=request_id)
                self._debug(request_id, "V7.plan_raw", plan=self._safe_plan_log(plan))

                # 4) Normalize
                plan = self._normalize_plan(plan, user_text=user_text)
                self._debug(request_id, "V7.plan_norm", plan=self._safe_plan_log(plan))

                # 5) Force product search if message looks product-ish
                if self._looks_like_product_query(user_text) and (plan.get("intent") in (None, "", "unknown")):
                    mods = self._parse_modifiers(user_text)
                    tags = self._token_tags(user_text)
                    for t in mods.get("tags") or []:
                        if t not in tags:
                            tags.append(t)

                    plan = {
                        "intent": "search_product",
                        "action": "SEARCH_PRODUCTS",
                        "category": None,
                        "product_name": self._normalize_text(user_text),
                        "postcode": None,
                        "sku": None,
                        "handoff_channel": None,
                        "needs_clarification": False,
                        "clarification_question": "",
                        "meta": {
                            "max_items": 12,
                            "search_tags": tags,
                            "sort": mods.get("sort"),
                            "max_price": mods.get("max_price"),
                            "required_terms": self._required_terms_from_text(user_text),
                        },
                    }
                    self._info(request_id, "V7.force_search_fallback", plan=self._safe_plan_log(plan))

            # 6) Execute
            facts = self._execute_plan(plan, user_text, session_snapshot, request_id=request_id)

            # 7) Entities
            entities = self._entities_from_plan(plan)

            # 8) Render
            reply_text = self.renderer.render(
                user_text=user_text,
                plan=plan,
                facts=facts,
                session=session_snapshot,
            )

            ui = {
                "has_catalog": bool(facts.get("items")),
                "catalog_items": self._format_items_for_ui(facts.get("items") or []),
            }

            dt_ms = int((time.perf_counter() - t0) * 1000)
            self._info(
                request_id,
                "V7.ok",
                intent=plan.get("intent"),
                action=plan.get("action"),
                items_count=len(facts.get("items") or []),
                facts_keys=list(facts.keys()),
                latency_ms=dt_ms,
            )

            return {
                "reply": reply_text,
                "mode": "v7",
                "intent": plan.get("intent"),
                "entities": entities,
                "facts": facts,
                "ui": ui,
                "meta": {"request_id": request_id, "latency_ms": dt_ms},
            }

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
    # POSTCODE HELPERS (NEW)
    # ------------------------------------------------------------------

    def _extract_postcode(self, text: str) -> Optional[str]:
        # normalize_postcode already handles spacing + comma inputs
        try:
            return normalize_postcode(text)
        except Exception:
            return None

    def _is_postcode_only(self, raw_text: str, normalized_pc: str) -> bool:
        t = (raw_text or "").strip().upper()
        pc = (normalized_pc or "").strip().upper()

        # Allow "E79QS" == "E7 9QS"
        t_compact = t.replace(" ", "")
        pc_compact = pc.replace(" ", "")

        return t_compact == pc_compact

    def _has_delivery_words(self, text: str) -> bool:
        tl = (text or "").lower()
        return any(w in tl for w in self._DELIVERY_WORDS)

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

        facts = {
            "items": merged,
            "groups": groups,
            "multi_meats": meats,
            "topic": topic,
        }
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

        if "chicken" not in found:
            if difflib.get_close_matches("chicken", t.split(), n=1, cutoff=0.78):
                for tok in t.split():
                    if difflib.get_close_matches(tok, ["chicken"], n=1, cutoff=0.78):
                        found.append("chicken")
                        break

        if "lamb" not in found:
            for tok in t.split():
                if difflib.get_close_matches(tok, ["lamb"], n=1, cutoff=0.78):
                    found.append("lamb")
                    break

        if "beef" not in found:
            for tok in t.split():
                if difflib.get_close_matches(tok, ["beef"], n=1, cutoff=0.78):
                    found.append("beef")
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
    # HEURISTICS
    # ------------------------------------------------------------------

    def _looks_like_product_query(self, user_text: str) -> bool:
        # ✅ NEW: if it's a postcode, it's NOT a product query
        if self._extract_postcode(user_text):
            return False

        t = self._clean_text(user_text)
        if not t:
            return False

        if len(t.split()) <= 7:
            return True

        for w in self._TOPIC_WORDS:
            if re.search(rf"\b{re.escape(w)}\b", t):
                return True

        if re.search(r"\b(cheapest|cheap|under|below|less than|£)\b", t):
            return True

        return False

    # --- everything below is your original code unchanged ---
    # (execute_plan, catalog search, post-filter, entities, UI, text normalization, logging...)
    # Keep the rest exactly as you had it.

    # ------------------------------------------------------------------
    # BRAIN WRAPPER + NORMALIZER
    # ------------------------------------------------------------------
    # (leave your existing _parse_modifiers, _heuristic_plan, _safe_plan, _normalize_plan,
    #  _execute_plan, _catalog_search_safe, _topic_enforce, _post_filter_items,
    #  _build_search_query, _entities_from_plan, _format_items_for_ui,
    #  _clean_text, _normalize_text, _fuzzy_fix_meat_token, _token_tags,
    #  _info/_debug/_exc/_compact/_clip/_safe_plan_log/_preview_items)
    #
    # IMPORTANT: do NOT remove your delivery logic in _execute_plan. We are now actually reaching it.
