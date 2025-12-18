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
    V7 handler (crash-proof + modifier-aware + multi-meat join)

    Guarantees:
    - Never crashes the webhook (hard try/except in handle + defensive helpers)
    - Strong heuristic for product queries, including typos + modifiers
    - Multi-meat join: "beef steaks lamb steaks and chicken steaks"
      runs per-meat searches and merges results (dedupe + optional sort/filter)
    - Always returns ui.catalog_items for webchat
    """

    # -----------------------------
    # ALIASES (expand freely)
    # -----------------------------
    # NOTE: This is token-based. Multi-word aliases are handled via regex rules too.
    _ALIASES: Dict[str, str] = {
        # meats (canonical keys)
        "chicken": "chicken",
        "poultry": "chicken",
        "hen": "chicken",
        "broiler": "chicken",
        "cockerel": "chicken",

        "lamb": "lamb",
        "mutton": "lamb",
        "sheep": "lamb",

        "beef": "beef",
        "cow": "beef",
        "veal": "beef",

        "goat": "goat",
        "kid": "goat",

        # common typos
        "chciken": "chicken",
        "chiken": "chicken",
        "chcken": "chicken",
        "chikcen": "chicken",
        "chikn": "chicken",
        "chkien": "chicken",

        "lam": "lamb",
        "lmb": "lamb",

        "bief": "beef",
        "bef": "beef",
        "beff": "beef",

        "chepest": "cheapest",
        "cheepest": "cheapest",
        "cheapest": "cheapest",
        "cheap": "cheapest",
        "lowest": "cheapest",
        "low": "cheapest",

        "expencive": "expensive",
        "expensive": "expensive",
        "premium": "expensive",
        "highest": "expensive",

        # cuts / intents
        "steak": "steak",
        "steaks": "steak",
        "ribeye": "ribeye",
        "rib-eye": "ribeye",
        "sirloin": "sirloin",
        "fillet": "fillet",
        "tbone": "tbone",
        "t-bone": "tbone",

        "mince": "mince",
        "ground": "mince",
        "keema": "mince",

        "chop": "chops",
        "chops": "chops",
        "rib": "ribs",
        "ribs": "ribs",

        "wing": "wings",
        "wings": "wings",
        "drumstick": "drumsticks",
        "drumsticks": "drumsticks",
        "thigh": "thighs",
        "thighs": "thighs",
        "breast": "breast",
        "breasts": "breast",
        "fillet(s)": "fillet",

        # organs / misc (helps searches)
        "kidney": "kidneys",
        "kidneys": "kidneys",
        "kindney": "kidneys",
        "kindneys": "kidneys",
        "kidnney": "kidneys",
        "kidnneys": "kidneys",
        "liver": "liver",
        "heart": "hearts",
        "hearts": "hearts",
        "tongue": "tongue",
        "tripe": "tripe",
        "brain": "brain",
        "paya": "paya",
        "feet": "feet",
        "head": "head",

        # modifiers / tags
        "bbq": "bbq",
        "barbecue": "bbq",
        "grill": "bbq",
        "grilled": "bbq",

        "marinated": "marinated",
        "marinaded": "marinated",
        "marinted": "marinated",
        "marinate": "marinated",

        "boneless": "boneless",
        "bonein": "bone_in",
        "bone-in": "bone_in",
        "bone": "bone_in",

        "skinon": "skin_on",
        "skin-on": "skin_on",
        "skinoff": "skin_off",
        "skin-off": "skin_off",

        "family": "family",
        "bulk": "bulk",
        "pack": "pack",
        "tray": "tray",
    }

    _MEAT_KEYS = ("chicken", "lamb", "beef", "goat")

    # phrases we strip for extracting "core" and intent
    _MOD_WORDS_RE = re.compile(
        r"\b("
        r"cheapest|cheap|lowest|low|"
        r"most\s+expensive|expensive|premium|highest|"
        r"under|below|less\s+than|"
        r"boneless|bbq|barbecue|marinated|marinaded|marinted|"
        r"family|bulk|pack|tray"
        r")\b",
        re.IGNORECASE,
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
        raw_text = (user_text or "").strip()

        request_id = self._get_request_id(ctx) or str(uuid.uuid4())[:12]
        tenant = getattr(ctx, "tenant", None) or "unknown"
        session_id = getattr(ctx, "session_id", None) or "unknown"
        channel = getattr(ctx, "channel", None) or "unknown"

        sess = sess or {}
        session_snapshot = {
            "postcode": sess.get("postcode"),
            "last_intent": sess.get("last_intent"),
            "last_category": sess.get("last_category"),
            "last_sku": sess.get("last_sku"),
        }

        # IMPORTANT: normalize early (this fixes multi-join + typos everywhere)
        norm_text = self._normalize_text(raw_text)

        self._info(
            request_id,
            "V7.start",
            tenant=tenant,
            session=session_id,
            channel=channel,
            text=self._clip(norm_text, 240),
            sess=session_snapshot,
        )

        try:
            # 0) MULTI-MEAT JOIN first (covers your main failing case)
            multi = self._multi_query_plan(norm_text, request_id=request_id)
            if multi:
                plan = multi["plan"]
                facts = multi["facts"]
                entities = self._entities_from_plan(plan)

                reply_text = self.renderer.render(
                    user_text=raw_text,
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

            # 1) Heuristic plan (short/medium product prompts)
            plan = self._heuristic_plan(norm_text, request_id=request_id)
            if plan:
                self._info(request_id, "V7.heuristic_used", plan=self._safe_plan_log(plan))
            else:
                # 2) Brain plan
                plan = self._safe_plan(user_text=raw_text, session=session_snapshot, request_id=request_id)
                self._debug(request_id, "V7.plan_raw", plan=self._safe_plan_log(plan))

                # 3) Normalize brain plan
                plan = self._normalize_plan(plan, user_text=raw_text)
                self._debug(request_id, "V7.plan_norm", plan=self._safe_plan_log(plan))

                # 4) Force product search fallback if it looks product-related
                if self._looks_like_product_query(norm_text) and (plan.get("intent") in (None, "", "unknown")):
                    mods = self._parse_modifiers(norm_text)
                    tags = self._token_tags(norm_text)
                    for t in mods.get("tags") or []:
                        if t not in tags:
                            tags.append(t)

                    plan = {
                        "intent": "search_product",
                        "action": "SEARCH_PRODUCTS",
                        "category": None,
                        "product_name": norm_text,
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
                        },
                    }
                    self._info(request_id, "V7.force_search_fallback", plan=self._safe_plan_log(plan))

            # 5) Execute
            facts = self._execute_plan(plan, raw_text, session_snapshot, request_id=request_id)

            # 6) Entities
            entities = self._entities_from_plan(plan)

            # 7) Render
            reply_text = self.renderer.render(
                user_text=raw_text,
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
    # NORMALIZATION
    # ------------------------------------------------------------------

    def _normalize_text(self, text: str) -> str:
        t = (text or "").lower().strip()
        if not t:
            return ""

        # unify separators
        t = t.replace("&", " and ")
        t = re.sub(r"[,/]+", " ", t)

        # keep £ and digits for "under £10"
        t = re.sub(r"[^a-z0-9\s£_-]+", " ", t)
        t = re.sub(r"\s+", " ", t).strip()

        toks = t.split()
        out: List[str] = []
        for tok in toks:
            out.append(self._ALIASES.get(tok, tok))
        t = " ".join(out).strip()

        # normalize a couple of common multiword forms
        t = re.sub(r"\bmost\s+expensive\b", "expensive", t)
        t = re.sub(r"\bless\s+than\b", "under", t)
        t = re.sub(r"\bskin\s+on\b", "skin_on", t)
        t = re.sub(r"\bskin\s+off\b", "skin_off", t)
        t = re.sub(r"\bbone\s+in\b", "bone_in", t)

        return re.sub(r"\s+", " ", t).strip()

    # ------------------------------------------------------------------
    # MULTI-MEAT JOIN (KEY FIX)
    # ------------------------------------------------------------------

    def _multi_query_plan(self, norm_text: str, request_id: str) -> Optional[Dict[str, Any]]:
        """
        Detect 2+ meats in a message and run per-meat searches, then merge.
        Example: "beef steaks lamb steaks and chicken steaks"
        """
        if not norm_text or not self.catalog:
            return None

        meats = self._extract_meats(norm_text)
        if len(meats) < 2:
            return None

        mods = self._parse_modifiers(norm_text)

        # Determine item intent like "steak", "mince", "chops", etc.
        item_intent = self._extract_item_intent(norm_text)

        # Build a "topic" by stripping meats + modifiers + glue words
        core = self._strip_meats_and_modifiers(norm_text, meats)
        topic = item_intent or core or "all"

        per_meat_limit = 8
        total_limit = 18

        merged: List[Dict[str, Any]] = []
        seen: set = set()

        for meat in meats:
            q = f"{meat} {topic}".strip()
            tags = self._token_tags(q)

            # ensure modifier tags are included
            for tag in mods.get("tags") or []:
                if tag not in tags:
                    tags.append(tag)

            self._info(request_id, "V7.multi.search", meat=meat, query=self._clip(q, 120), tags=tags[:20])

            try:
                items = self.catalog.search(text=q, tags=tags, limit=per_meat_limit) or []
            except Exception as e:
                self._exc(request_id, "V7.multi.search_failed", err=str(e), meat=meat)
                items = []

            items = self._post_filter_items(items, {"max_price": mods.get("max_price"), "sort": mods.get("sort")})

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
            "product_name": norm_text,
            "postcode": None,
            "sku": None,
            "handoff_channel": None,
            "needs_clarification": False,
            "clarification_question": "",
            "meta": {
                "max_items": total_limit,
                "search_tags": self._token_tags(norm_text),
                "sort": mods.get("sort"),
                "max_price": mods.get("max_price"),
                "multi_meats": meats,
                "topic": topic,
            },
        }

        facts = {"items": merged}
        self._info(request_id, "V7.multi.merged", meats=meats, topic=topic, count=len(merged))
        return {"plan": plan, "facts": facts}

    def _extract_meats(self, norm_text: str) -> List[str]:
        t = norm_text or ""
        found: List[str] = []
        for k in self._MEAT_KEYS:
            if re.search(rf"\b{re.escape(k)}\b", t):
                found.append(k)
        # dedupe
        out: List[str] = []
        for x in found:
            if x not in out:
                out.append(x)
        return out

    def _extract_item_intent(self, norm_text: str) -> Optional[str]:
        """
        Detect the product-type the user is asking for:
        steak/mince/chops/wings/etc.
        """
        t = norm_text or ""

        # priority matters (specific before generic)
        intents = [
            "ribeye", "sirloin", "fillet", "tbone",  # specific steaks
            "steak",
            "mince",
            "chops",
            "wings", "drumsticks", "thighs", "breast",
            "ribs",
            "kofta",
            "boneless",
            "marinated",
            "bbq",
        ]
        for it in intents:
            if re.search(rf"\b{re.escape(it)}\b", t):
                return it
        return None

    def _strip_meats_and_modifiers(self, norm_text: str, meats: List[str]) -> str:
        s = norm_text or ""
        # remove modifiers
        s = self._MOD_WORDS_RE.sub(" ", s)
        # remove meats
        for m in meats:
            s = re.sub(rf"\b{re.escape(m)}\b", " ", s)
        # remove glue
        s = re.sub(r"\b(and|or|with|plus)\b", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    # ------------------------------------------------------------------
    # HEURISTICS
    # ------------------------------------------------------------------

    def _looks_like_product_query(self, norm_text: str) -> bool:
        if not norm_text:
            return False
        return len(norm_text.split()) <= 9  # allow "beef ribeye steak under 10"

    def _parse_modifiers(self, norm_text: str) -> Dict[str, Any]:
        t = norm_text or ""

        sort = None
        if re.search(r"\bcheapest\b|\bcheap\b|\blowest\b|\blow\b", t):
            sort = "price_asc"
        if re.search(r"\bexpensive\b|\bpremium\b|\bhighest\b", t):
            sort = "price_desc"

        max_price = None
        m = re.search(r"\b(under|below)\s*£?\s*(\d+(\.\d+)?)\b", t)
        if m:
            try:
                max_price = float(m.group(2))
            except Exception:
                max_price = None

        tags: List[str] = []
        for tag in ("bbq", "marinated", "boneless", "family", "bulk"):
            if re.search(rf"\b{re.escape(tag)}\b", t):
                tags.append(tag)

        return {"sort": sort, "max_price": max_price, "tags": tags}

    def _token_tags(self, norm_text: str) -> List[str]:
        t = (norm_text or "").lower()
        t = re.sub(r"[^a-z0-9\s_]+", " ", t)
        toks = [x.strip() for x in t.split() if x.strip()]
        out: List[str] = []
        for tok in toks:
            if tok not in out:
                out.append(tok)
        return out

    def _heuristic_plan(self, norm_text: str, request_id: str) -> Optional[Dict[str, Any]]:
        """
        Heuristic for product searching:
        - short/medium prompts
        - typos are already normalized
        - supports "cheapest lamb", "lamb under 10", "bbq chicken wings"
        """
        if not norm_text:
            return None
        if len(norm_text.split()) > 9:
            return None

        mods = self._parse_modifiers(norm_text)

        # If it looks like product-y text, force SEARCH_PRODUCTS (no clarification blocking)
        if self._looks_like_product_query(norm_text):
            tags = self._token_tags(norm_text)
            for t in mods.get("tags") or []:
                if t not in tags:
                    tags.append(t)

            # if user wrote only "under 10" etc., keep tags as query
            query = norm_text
            if mods.get("max_price") is not None:
                # remove "under 10" from query so search focuses on items
                query = re.sub(r"\b(under|below)\s*£?\s*\d+(\.\d+)?\b", " ", query)
                query = re.sub(r"\s+", " ", query).strip() or norm_text

            return {
                "intent": "search_product",
                "action": "SEARCH_PRODUCTS",
                "category": None,
                "product_name": query,
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
                },
            }

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

        if (category or product_name) and action in {"", "DO_NOTHING", "STORE_INFO", "FAQ_LOOKUP"}:
            p["action"] = "SEARCH_PRODUCTS"
            if (p.get("intent") or "").strip().lower() in {"", "unknown"}:
                p["intent"] = "browse_category" if category and not product_name else "search_product"

        # don't block on clarification for short/medium product messages
        if len((user_text or "").split()) <= 9 and p.get("needs_clarification"):
            p["needs_clarification"] = False
            p["clarification_question"] = ""

        meta = p.get("meta") or {}
        if not isinstance(meta, dict):
            meta = {}
        meta.setdefault("max_items", 12)
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

    def _post_filter_items(self, items: List[Dict[str, Any]], meta: Dict[str, Any]) -> List[Dict[str, Any]]:
        meta = meta or {}
        max_price = meta.get("max_price")
        sort = meta.get("sort")

        cleaned: List[Dict[str, Any]] = [it for it in (items or []) if isinstance(it, dict)]

        # filter: max_price
        if isinstance(max_price, (int, float)):
            tmp: List[Dict[str, Any]] = []
            for it in cleaned:
                p = it.get("price")
                try:
                    p_val = float(p) if p is not None else None
                except Exception:
                    p_val = None
                # keep unknown prices, but filter known ones
                if p_val is None or p_val <= float(max_price):
                    tmp.append(it)
            cleaned = tmp

        # sort
        if sort in {"price_asc", "price_desc"}:
            def price_key(x: Dict[str, Any]) -> float:
                try:
                    return float(x.get("price"))
                except Exception:
                    return 10**9

            cleaned.sort(key=price_key, reverse=(sort == "price_desc"))

        return cleaned

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
            query, tags = self._build_search_query(user_text, category, product_name, meta)

            try:
                limit = int((meta or {}).get("max_items") or 12)
            except Exception:
                limit = 12

            self._info(
                request_id,
                "V7.catalog.search",
                query=self._clip(query, 120),
                tags=(tags or [])[:20],
                limit=limit,
                meta=self._compact(meta),
            )

            items: List[Dict[str, Any]] = []
            if self.catalog and (query or tags):
                try:
                    items = self.catalog.search(text=query, tags=tags, limit=limit) or []
                except Exception as e:
                    self._exc(request_id, "V7.catalog.search_failed", err=str(e))
                    items = []
            else:
                if not self.catalog:
                    self._debug(request_id, "V7.catalog_missing")
                else:
                    self._debug(request_id, "V7.catalog_search_skipped", query=query, tags=tags)

            items = self._post_filter_items(items, meta)
            facts["items"] = items
            self._debug(request_id, "V7.catalog.result", count=len(items), preview=self._preview_items(items))

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

        if not category and not product_name and tags:
            query = " ".join(tags)

        return (query or "").strip(), tags

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
