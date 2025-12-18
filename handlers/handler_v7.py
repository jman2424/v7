# handlers/handler_v7.py
from __future__ import annotations

import difflib
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from brain_v7 import BrainV7
from renderer_v7 import RendererV7


class MessageHandlerV7:
    """
    V7 handler (AI-guided, minimal hardcoding, crash-proof)

    Principles:
    - Let BrainV7 do the "understanding" (intent, modifiers, multi-queries).
    - Keep code responsible for:
        * safety (never crash)
        * schema validation (plan sanitizer)
        * executing catalog / delivery / faq
        * multi-search merge + retry when query returns 0
        * post-filter/sort (cheapest, under £X, boneless, bbq, marinated)
    - Avoid huge alias tables. Use:
        * dynamic fuzzy match against catalog categories
        * small stable keyword lists (greetings, meats, modifiers)
    """

    # Small stable lists (not tied to your catalog contents)
    _MEATS = ("chicken", "lamb", "beef", "goat")
    _CONJ = ("and", "or", "with", "plus", "&", ",")
    _GREETINGS = {
        "hi", "hello", "hey", "yo", "salam", "assalamualaikum", "asalamualaikum",
        "good morning", "good afternoon", "good evening"
    }

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
            # 0) greetings / small talk should NOT call catalog
            if self._is_greeting(user_text):
                plan = {
                    "intent": "greeting",
                    "action": "DO_NOTHING",
                    "category": None,
                    "product_name": None,
                    "postcode": session_snapshot.get("postcode"),
                    "sku": None,
                    "handoff_channel": None,
                    "needs_clarification": False,
                    "clarification_question": "",
                    "meta": {"max_items": 0},
                }
                facts: Dict[str, Any] = {}
                reply_text = self.renderer.render(
                    user_text=user_text,
                    plan=plan,
                    facts=facts,
                    session=session_snapshot,
                )
                return self._ok_payload(request_id, t0, plan, facts, reply_text)

            # 1) quick delivery intent (postcode)
            # e.g. "delivery to E1 6AN"
            if self._looks_like_delivery_query(user_text):
                plan = {
                    "intent": "check_delivery",
                    "action": "CHECK_DELIVERY",
                    "category": None,
                    "product_name": None,
                    "postcode": self._extract_postcode(user_text) or session_snapshot.get("postcode"),
                    "sku": None,
                    "handoff_channel": None,
                    "needs_clarification": False,
                    "clarification_question": "",
                    "meta": {"max_items": 0},
                }
                facts = self._execute_plan(plan, user_text, session_snapshot, request_id=request_id)
                reply_text = self.renderer.render(
                    user_text=user_text,
                    plan=plan,
                    facts=facts,
                    session=session_snapshot,
                )
                return self._ok_payload(request_id, t0, plan, facts, reply_text)

            # 2) Ask BrainV7 for a plan (AI intelligence lives here)
            plan = self._safe_plan(user_text=user_text, session=session_snapshot, request_id=request_id)
            plan = self._sanitize_plan(plan, user_text=user_text, request_id=request_id)
            self._debug(request_id, "V7.plan", plan=self._safe_plan_log(plan))

            # 3) If it looks product-related, allow multi-search join (thin deterministic layer)
            if self._looks_like_product_query(user_text):
                multi = self._maybe_multi_search(plan, user_text, request_id=request_id)
                if multi is not None:
                    facts = {"items": multi}
                    reply_text = self.renderer.render(
                        user_text=user_text,
                        plan=plan,
                        facts=facts,
                        session=session_snapshot,
                    )
                    return self._ok_payload(request_id, t0, plan, facts, reply_text)

            # 4) Normal execution
            facts = self._execute_plan(plan, user_text, session_snapshot, request_id=request_id)

            # 5) Render
            reply_text = self.renderer.render(
                user_text=user_text,
                plan=plan,
                facts=facts,
                session=session_snapshot,
            )

            return self._ok_payload(request_id, t0, plan, facts, reply_text)

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
    # SUCCESS PAYLOAD
    # ------------------------------------------------------------------

    def _ok_payload(self, request_id: str, t0: float, plan: Dict[str, Any], facts: Dict[str, Any], reply_text: str) -> Dict[str, Any]:
        dt_ms = int((time.perf_counter() - t0) * 1000)
        entities = self._entities_from_plan(plan)
        ui = {
            "has_catalog": bool((facts or {}).get("items")),
            "catalog_items": self._format_items_for_ui((facts or {}).get("items") or []),
        }
        self._info(
            request_id,
            "V7.ok",
            intent=plan.get("intent"),
            action=plan.get("action"),
            items_count=len((facts or {}).get("items") or []),
            facts_keys=list((facts or {}).keys()),
            latency_ms=dt_ms,
        )
        return {
            "reply": reply_text,
            "mode": "v7",
            "intent": plan.get("intent"),
            "entities": entities,
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
    # AI PLAN (INTELLIGENCE)
    # ------------------------------------------------------------------

    def _safe_plan(self, user_text: str, session: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        """
        Let BrainV7 interpret the message.
        Provide hints (categories + synonyms) but never crash if any hint fails.
        """
        try:
            hints: Dict[str, Any] = {}

            if self.catalog:
                try:
                    cats = self.catalog.categories() or []
                    hints["categories"] = [
                        {"id": c.get("id"), "name": c.get("name")}
                        for c in cats
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
            return plan if isinstance(plan, dict) else {}

        except Exception as e:
            self._exc(request_id, "V7.brain_plan_failed", err=str(e))
            return {}

    def _sanitize_plan(self, plan: Dict[str, Any], user_text: str, request_id: str) -> Dict[str, Any]:
        """
        Never trust LLM output.
        - guarantee required keys
        - force SEARCH_PRODUCTS for product-looking text
        - handle category fuzzy match if category looks like a typo
        """
        p = dict(plan or {})

        # defaults
        p.setdefault("intent", "unknown")
        p.setdefault("action", "DO_NOTHING")
        p.setdefault("category", None)
        p.setdefault("product_name", None)
        p.setdefault("postcode", None)
        p.setdefault("sku", None)
        p.setdefault("handoff_channel", None)
        p.setdefault("needs_clarification", False)
        p.setdefault("clarification_question", "")
        meta = p.get("meta") if isinstance(p.get("meta"), dict) else {}
        meta.setdefault("max_items", 12)
        p["meta"] = meta

        # normalize action
        action = str(p.get("action") or "").strip().upper()
        if action not in {"DO_NOTHING", "SEARCH_PRODUCTS", "CHECK_DELIVERY", "PRICE_CHECK", "STORE_INFO", "FAQ_LOOKUP"}:
            action = "DO_NOTHING"
        p["action"] = action

        # If user_text is producty, force search even if brain was weak
        if self._looks_like_product_query(user_text):
            # allow brain to keep CHECK_DELIVERY / PRICE_CHECK if it chose those
            if p["action"] in {"DO_NOTHING", "STORE_INFO", "FAQ_LOOKUP"}:
                p["action"] = "SEARCH_PRODUCTS"
                if p.get("intent") in (None, "", "unknown"):
                    p["intent"] = "search_product"

        # If category exists but might be typo, fuzzy-match to real category id
        if p.get("category") and self.catalog:
            try:
                cat_fixed = self._fuzzy_category_match(str(p["category"]), request_id=request_id)
                if cat_fixed:
                    p["category"] = cat_fixed
            except Exception:
                pass

        # If brain wants clarification on short/medium prompt, don't block results
        if len((user_text or "").split()) <= 8 and p.get("needs_clarification"):
            p["needs_clarification"] = False
            p["clarification_question"] = ""

        return p

    # ------------------------------------------------------------------
    # MULTI SEARCH JOIN (DETERMINISTIC EXECUTION LAYER)
    # ------------------------------------------------------------------

    def _maybe_multi_search(self, plan: Dict[str, Any], user_text: str, request_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        If the user asks for multiple meats/topics in one message, do multiple searches and merge.
        This avoids relying on catalog.search to magically understand "beef and lamb steak".
        """
        if not self.catalog:
            return None

        parsed = self._parse_product_query(user_text)
        if parsed is None:
            return None

        meats = parsed["meats"]
        topics = parsed["topics"]
        mods = parsed["mods"]

        # If not actually multi, return None (normal single search will handle it)
        if len(meats) < 2 and len(topics) < 2:
            return None

        per_search_limit = 7
        total_limit = int((plan.get("meta") or {}).get("max_items") or 14)
        total_limit = max(8, min(total_limit, 24))

        merged: List[Dict[str, Any]] = []
        seen = set()

        # Build clauses
        clauses: List[str] = []
        if meats and topics:
            for m in meats:
                for t in topics:
                    clauses.append(f"{m} {t}".strip())
        elif meats:
            # user asked "beef and lamb" only
            for m in meats:
                clauses.append(m)
        else:
            # topics only (rare)
            for t in topics:
                clauses.append(t)

        for clause in clauses:
            items = self._search_with_retry(clause, mods, limit=per_search_limit, request_id=request_id)
            for it in items:
                if not isinstance(it, dict):
                    continue
                key = (it.get("sku") or it.get("id") or it.get("code") or it.get("name") or "").strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(it)

        merged = self._post_filter_items(merged, mods)
        return merged[:total_limit]

    def _search_with_retry(self, clause: str, mods: Dict[str, Any], limit: int, request_id: str) -> List[Dict[str, Any]]:
        """
        Search strategy:
        - try clause as text+tags
        - if 0 results, retry with a looser version (drop topic words, keep meat)
        """
        clause = self._clean_text(clause)
        tags = self._tokenize(clause)
        for t in mods.get("tags") or []:
            if t not in tags:
                tags.append(t)

        self._info(request_id, "V7.multi.search", clause=self._clip(clause, 120), tags=tags[:20], limit=limit)
        items = self._catalog_search_safe(clause, tags, limit, request_id)

        if items:
            return self._post_filter_items(items, mods)

        # Retry: keep only meat token if present (looser)
        meat_only = self._extract_first_meat(clause) or clause.split(" ")[0]
        meat_only = self._clean_text(meat_only)
        tags2 = self._tokenize(meat_only)
        for t in mods.get("tags") or []:
            if t not in tags2:
                tags2.append(t)

        self._info(request_id, "V7.multi.retry", clause=self._clip(meat_only, 120), tags=tags2[:20], limit=limit)
        items2 = self._catalog_search_safe(meat_only, tags2, limit, request_id)
        return self._post_filter_items(items2, mods)

    def _catalog_search_safe(self, text: str, tags: List[str], limit: int, request_id: str) -> List[Dict[str, Any]]:
        if not self.catalog or (not text and not tags):
            return []
        try:
            return self.catalog.search(text=text, tags=tags, limit=limit) or []
        except Exception as e:
            self._exc(request_id, "V7.catalog.search_failed", err=str(e), text=self._clip(text, 120), tags=(tags or [])[:20])
            return []

    # ------------------------------------------------------------------
    # EXECUTION (single-plan)
    # ------------------------------------------------------------------

    def _execute_plan(self, plan: Dict[str, Any], user_text: str, session: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        facts: Dict[str, Any] = {}

        action = (plan.get("action") or "DO_NOTHING").strip().upper()
        intent = (plan.get("intent") or "unknown").strip().lower()
        meta = plan.get("meta") or {}

        category = plan.get("category")
        product_name = plan.get("product_name") or None
        postcode = plan.get("postcode") or session.get("postcode")
        sku = plan.get("sku")

        # DELIVERY
        if action == "CHECK_DELIVERY" or intent == "check_delivery":
            if self.policy and postcode:
                try:
                    rule = self.policy.delivery_rule_for(postcode)
                    summary = self.policy.delivery_summary(postcode)
                except Exception as e:
                    self._exc(request_id, "V7.delivery_failed", err=str(e))
                    rule, summary = None, ""
                facts["delivery"] = {"postcode": postcode, "rule": rule, "summary": summary or ""}

            if self.geo and postcode:
                try:
                    nb = self.geo.nearest_for_postcode(postcode)
                except Exception as e:
                    self._exc(request_id, "V7.geo_failed", err=str(e))
                    nb = None
                if nb:
                    facts.setdefault("branch", {})["nearest"] = nb

        # PRODUCTS
        if action == "SEARCH_PRODUCTS" or intent in {"search_product", "browse_category"}:
            mods = self._parse_modifiers(user_text)
            query, tags = self._build_search_query(user_text, category, product_name, meta)

            try:
                limit = int((meta or {}).get("max_items") or 12)
            except Exception:
                limit = 12

            self._info(request_id, "V7.catalog.search", query=self._clip(query, 120), tags=(tags or [])[:20], limit=limit)

            items = self._catalog_search_safe(query, tags, limit, request_id)
            items = self._post_filter_items(items, mods)
            facts["items"] = items

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

    # ------------------------------------------------------------------
    # PARSING (small stable heuristics)
    # ------------------------------------------------------------------

    def _is_greeting(self, text: str) -> bool:
        t = self._clean_text(text)
        if not t:
            return False
        if t in self._GREETINGS:
            return True
        # handle "hello bro" etc.
        for g in self._GREETINGS:
            if t.startswith(g + " "):
                return True
        return False

    def _looks_like_delivery_query(self, text: str) -> bool:
        t = (text or "").lower()
        return ("deliver" in t or "delivery" in t) and bool(self._extract_postcode(text))

    def _extract_postcode(self, text: str) -> Optional[str]:
        # basic UK postcode pattern (good enough for routing; policy service should validate)
        t = (text or "").upper()
        m = re.search(r"\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s*(\d[A-Z]{2})\b", t)
        if not m:
            return None
        return f"{m.group(1)} {m.group(2)}".strip()

    def _looks_like_product_query(self, text: str) -> bool:
        t = self._clean_text(text)
        if not t:
            return False
        if self._is_greeting(t):
            return False
        # if it contains product-ish words or any meat word, it's producty
        if any(re.search(rf"\b{m}\b", t) for m in self._MEATS):
            return True
        if re.search(r"\b(steak|steaks|chops|mince|wings|breast|thigh|drumstick|ribs|boneless|marinated|bbq|cheap|cheapest|under|below)\b", t):
            return True
        # short messages like "lamb" "wings" are producty
        return len(t.split()) <= 3

    def _parse_product_query(self, text: str) -> Optional[Dict[str, Any]]:
        t = self._clean_text(text)
        if not t:
            return None

        mods = self._parse_modifiers(t)

        # find meats mentioned
        meats = [m for m in self._MEATS if re.search(rf"\b{m}\b", t)]
        # if user typed “poultry”, treat it as chicken without huge alias list
        if "chicken" not in meats and re.search(r"\bpoultry\b", t):
            meats.append("chicken")
        if "lamb" not in meats and re.search(r"\bmutton\b", t):
            meats.append("lamb")

        # topics: remove meats + modifiers + connectors; remaining nouns become topic tokens
        core = self._strip_modifiers(t)
        core = re.sub(r"\b(and|or|with|plus)\b", " ", core)
        for m in meats:
            core = re.sub(rf"\b{re.escape(m)}\b", " ", core)
        core = re.sub(r"\s+", " ", core).strip()

        topics: List[str] = []
        if core:
            # split core by connectors into possible topics
            parts = re.split(r"\b(and|or|with|plus)\b|,", core)
            parts = [p.strip() for p in parts if p and p.strip() and p.strip() not in self._CONJ]
            # “steaks” “steak” etc -> keep as is; don’t over-normalize
            topics = parts[:3]

        # If user gave "beef and lamb steak", core should be "steak"
        # If user gave "beef steaks lamb steaks and chicken steaks", core might be "steaks"
        if not topics and re.search(r"\bsteak(s)?\b", t):
            topics = ["steak"]

        return {"meats": meats, "topics": topics, "mods": mods}

    def _extract_first_meat(self, text: str) -> Optional[str]:
        t = (text or "").lower()
        for m in self._MEATS:
            if re.search(rf"\b{m}\b", t):
                return m
        if re.search(r"\bpoultry\b", t):
            return "chicken"
        if re.search(r"\bmutton\b", t):
            return "lamb"
        return None

    def _parse_modifiers(self, text: str) -> Dict[str, Any]:
        t = (text or "").lower()

        sort = None
        if re.search(r"\b(cheapest|cheap|lowest)\b", t):
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

    def _strip_modifiers(self, text: str) -> str:
        s = (text or "").lower()
        s = re.sub(
            r"\b(cheapest|cheap|lowest|most|expensive|highest|premium|"
            r"under|below|less|than|boneless|bbq|barbecue|marinated|marinted)\b",
            " ",
            s,
        )
        s = s.replace("£", " ")
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _clean_text(self, text: str) -> str:
        t = (text or "").lower().strip()
        t = re.sub(r"[^a-z0-9\s£_-]+", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _tokenize(self, text: str) -> List[str]:
        t = self._clean_text(text)
        toks = [x for x in t.split() if x]
        out: List[str] = []
        for tok in toks:
            if tok not in out:
                out.append(tok)
        return out

    # ------------------------------------------------------------------
    # CATEGORY FUZZY MATCH (dynamic, no alias tables)
    # ------------------------------------------------------------------

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

        t = self._clean_text(text)
        if t in id_map:
            return id_map[t]

        match = difflib.get_close_matches(t, candidates, n=1, cutoff=0.78)
        if match:
            return id_map.get(match[0]) or match[0]
        return None

    # ------------------------------------------------------------------
    # SEARCH QUERY BUILD + POST FILTER/SORT
    # ------------------------------------------------------------------

    def _build_search_query(self, user_text: str, category: Optional[str], product_name: Optional[str], meta: Dict[str, Any]) -> Tuple[str, List[str]]:
        tags: List[str] = []
        query = ""

        meta = meta or {}
        meta_tags = meta.get("search_tags") or []
        if isinstance(meta_tags, str):
            meta_tags = [meta_tags]
        for t in meta_tags:
            tt = self._clean_text(str(t))
            if tt and tt not in tags:
                tags.append(tt)

        if product_name:
            query = str(product_name).strip()
        elif category:
            cat_key = self._clean_text(str(category))
            query = cat_key.replace("_", " ")
            if cat_key and cat_key not in tags:
                tags.append(cat_key)
            for token in re.split(r"[ _]+", cat_key):
                if token and token not in tags:
                    tags.append(token)
        else:
            query = (user_text or "").strip()

        # add tokens from query
        for tok in self._tokenize(query):
            if tok not in tags:
                tags.append(tok)

        return self._clean_text(query), tags

    def _post_filter_items(self, items: List[Dict[str, Any]], mods: Dict[str, Any]) -> List[Dict[str, Any]]:
        mods = mods or {}
        max_price = mods.get("max_price")
        sort = mods.get("sort")

        cleaned: List[Dict[str, Any]] = [it for it in (items or []) if isinstance(it, dict)]

        # tag filtering (soft): if boneless/bbq/marinated requested, prefer those
        want_tags = mods.get("tags") or []
        if want_tags:
            preferred: List[Dict[str, Any]] = []
            other: List[Dict[str, Any]] = []
            for it in cleaned:
                it_tags = it.get("tags") or []
                it_name = (it.get("name") or "").lower()
                score = 0
                for wt in want_tags:
                    if wt in it_tags or wt in it_name:
                        score += 1
                (preferred if score > 0 else other).append(it)
            cleaned = preferred + other

        # filter: max_price (best effort)
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

        # sort by price
        if sort in {"price_asc", "price_desc"}:
            def price_key(x: Dict[str, Any]) -> float:
                try:
                    return float(x.get("price"))
                except Exception:
                    return 10**9

            cleaned.sort(key=price_key, reverse=(sort == "price_desc"))

        return cleaned

    # ------------------------------------------------------------------
    # ENTITIES + UI
    # ------------------------------------------------------------------

    def _entities_from_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        entities: Dict[str, Any] = {}
        if plan.get("category"):
            entities["category"] = plan["category"]
        if plan.get("postcode"):
            entities["postcode"] = plan["postcode"]
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
    # LOGGING (never crash)
    # ------------------------------------------------------------------

    def _info(self, rid: str, msg: str, **fields: Any) -> None:
        if not self.logger:
            return
        try:
            self.logger.info("%s | %s | %s", rid, msg, self._compact(fields))
        except Exception:
            pass

    def _debug(self, rid: str, msg: str, **fields: Any) -> None:
        if not self.logger:
            return
        try:
            self.logger.debug("%s | %s | %s", rid, msg, self._compact(fields))
        except Exception:
            pass

    def _exc(self, rid: str, msg: str, **fields: Any) -> None:
        if not self.logger:
            return
        try:
            self.logger.exception("%s | %s | %s", rid, msg, self._compact(fields))
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
        keep = ("intent", "action", "category", "product_name", "postcode", "sku", "needs_clarification", "meta")
        out: Dict[str, Any] = {}
        for k in keep:
            if k in plan:
                out[k] = plan.get(k)
        return out
