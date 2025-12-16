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
    V7 handler (crash-proof + modifier-aware + multi-category join)

    Fixes:
    - Never crash the webhook (hard try/except + defensive helpers)
    - Heuristics cover short + medium prompts (<= 7 words):
        * typos: "lam", "chciken", "chepest", "kidnneys"
        * modifiers: "cheapest lamb", "lamb under 10", "boneless lamb", "bbq chicken", "marinted chicken"
        * multi-category queries: "beef steaks lamb steaks and chicken steaks"
    - Forces SEARCH_PRODUCTS when message looks product-related
    - Post-filter + post-sort applied even if catalog.search doesn't support it
    - Always returns ui.catalog_items for webchat cards
    - Strong request_id logging
    """

    # -----------------------------
    # ALIASES / NORMALIZATION
    # -----------------------------
    # Expand these freely; they are safe and cheap.
    _MEAT_ALIASES: Dict[str, str] = {
        # chicken / poultry
        "chicken": "chicken",
        "chciken": "chicken",
        "chiken": "chicken",
        "chcken": "chicken",
        "chikcen": "chicken",
        "chikn": "chicken",
        "poultry": "chicken",
        "hen": "chicken",
        "broiler": "chicken",
        "wings": "wings",
        "wing": "wings",
        "drumstick": "drumsticks",
        "drumsticks": "drumsticks",
        "thigh": "thighs",
        "thighs": "thighs",
        "breast": "breast",
        "breasts": "breast",
        "fillet": "fillet",
        "fillets": "fillet",
        "whole chicken": "whole",

        # lamb
        "lamb": "lamb",
        "lam": "lamb",
        "lambs": "lamb",
        "mutton": "lamb",
        "goat": "goat",
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
        "paya": "paya",
        "feet": "feet",
        "head": "head",
        "brain": "brain",

        # beef
        "beef": "beef",
        "bief": "beef",
        "bef": "beef",
        "cow": "beef",
        "steak": "steak",
        "steaks": "steak",
        "sirloin": "sirloin",
        "ribeye": "ribeye",
        "fillet steak": "fillet",
        "fillet steak(s)": "fillet",

        # generic cuts / intents
        "mince": "mince",
        "ground": "mince",
        "chops": "chops",
        "chop": "chops",
        "ribs": "ribs",
        "rib": "ribs",
        "bbq": "bbq",
        "barbecue": "bbq",
        "marinated": "marinated",
        "marinaded": "marinated",
        "marinted": "marinated",
        "marin(t|e)ed": "marinated",
        "boneless": "boneless",
        "bone-in": "bone_in",
        "bone in": "bone_in",
        "skin on": "skin_on",
        "skin off": "skin_off",

        # cheap typos for modifiers
        "cheapest": "cheapest",
        "chepest": "cheapest",
        "cheap": "cheapest",
        "lowest": "cheapest",
        "low": "cheapest",
        "most expensive": "expensive",
        "highest": "expensive",
        "premium": "expensive",
        "best": "best",
        "family": "family",
        "family pack": "family",
        "bulk": "bulk",
    }

    _MEAT_KEYS = ("chicken", "lamb", "beef", "goat")

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
            # 0) Multi-category join (e.g., "beef steaks lamb steaks and chicken steaks")
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
                self._info(
                    request_id,
                    "V7.ok_multi",
                    items_count=len(facts.get("items") or []),
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

            # 1) Heuristic (handles failing cases)
            plan = self._heuristic_plan(user_text, request_id=request_id)
            if plan:
                self._info(request_id, "V7.heuristic_used", plan=self._safe_plan_log(plan))
            else:
                # 2) Brain plan
                plan = self._safe_plan(user_text=user_text, session=session_snapshot, request_id=request_id)
                self._debug(request_id, "V7.plan_raw", plan=self._safe_plan_log(plan))

                # 3) Normalize
                plan = self._normalize_plan(plan, user_text=user_text)
                self._debug(request_id, "V7.plan_norm", plan=self._safe_plan_log(plan))

                # 4) Force product search for product-looking messages
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
                        },
                    }
                    self._info(request_id, "V7.force_search_fallback", plan=self._safe_plan_log(plan))

            # 5) Execute tools
            facts = self._execute_plan(plan, user_text, session_snapshot, request_id=request_id)

            # 6) Entities
            entities = self._entities_from_plan(plan)

            # 7) Render
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
    # MULTI CATEGORY JOIN (KEY PATCH)
    # ------------------------------------------------------------------

    def _multi_query_plan(self, user_text: str, request_id: str) -> Optional[Dict[str, Any]]:
        """
        If user asked for the same thing across multiple meats:
          - "beef steaks lamb steaks and chicken steaks"
          - "lamb mince and beef mince"
          - "chicken wings and lamb chops"
        We run multiple searches and merge.
        """
        text = (user_text or "").strip().lower()
        if not text or not self.catalog:
            return None

        meats = self._extract_meats(text)
        if len(meats) < 2:
            return None

        mods = self._parse_modifiers(text)

        # topic/cut words left after removing meats + conjunctions + modifier words
        core = self._strip_modifier_words(text)
        core = re.sub(r"\b(and|or|with|plus)\b", " ", core)
        for m in meats:
            core = re.sub(rf"\b{re.escape(m)}\b", " ", core)
        core = re.sub(r"\s+", " ", core).strip()

        # If nothing left, default to "all" to pull general lists for each meat
        topic = core or "all"

        # Build searches per meat
        merged: List[Dict[str, Any]] = []
        seen: set = set()

        # More results per meat, then post-filter + cap total
        per_meat_limit = 8
        total_limit = 18

        for meat in meats:
            q = f"{meat} {topic}".strip()
            tags = self._token_tags(f"{meat} {topic}")
            # add modifier tags (bbq/marinated/boneless)
            for t in mods.get("tags") or []:
                if t not in tags:
                    tags.append(t)

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
                if not key:
                    continue
                if key in seen:
                    continue
                seen.add(key)
                merged.append(it)

        merged = self._post_filter_items(merged, {"max_price": mods.get("max_price"), "sort": mods.get("sort")})
        merged = merged[:total_limit]

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
                "max_items": total_limit,
                "search_tags": self._token_tags(user_text),
                "sort": mods.get("sort"),
                "max_price": mods.get("max_price"),
                "multi_meats": meats,
                "topic": topic,
            },
        }

        facts = {"items": merged}
        self._info(request_id, "V7.multi.merged", meats=meats, topic=topic, count=len(merged))
        return {"plan": plan, "facts": facts}

    def _extract_meats(self, text: str) -> List[str]:
        t = (text or "").lower()
        found: List[str] = []
        for k in self._MEAT_KEYS:
            if re.search(rf"\b{re.escape(k)}\b", t):
                found.append(k)
        # also map common alias words if user typed only alias forms
        # e.g. "poultry steaks" -> include chicken
        if "chicken" not in found and re.search(r"\bpoultry\b", t):
            found.append("chicken")
        if "lamb" not in found and re.search(r"\bmutton\b", t):
            found.append("lamb")
        return found

    # ------------------------------------------------------------------
    # HEURISTICS
    # ------------------------------------------------------------------

    def _looks_like_product_query(self, user_text: str) -> bool:
        text = (user_text or "").strip().lower()
        if not text:
            return False
        return len(text.split()) <= 7

    def _normalize_text(self, text: str) -> str:
        t = (text or "").lower().strip()
        t = re.sub(r"[^a-z0-9\s£_-]+", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        # apply alias replacements token-by-token
        toks = t.split()
        out: List[str] = []
        for tok in toks:
            out.append(self._MEAT_ALIASES.get(tok, tok))
        return " ".join(out).strip()

    def _parse_modifiers(self, text: str) -> Dict[str, Any]:
        t = (text or "").lower()

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
        if re.search(r"\bfamily\b|\bfamily pack\b", t):
            tags.append("family")
        if re.search(r"\bbulk\b", t):
            tags.append("bulk")

        return {"sort": sort, "max_price": max_price, "tags": tags}

    def _strip_modifier_words(self, text: str) -> str:
        s = (text or "").lower()
        s = re.sub(
            r"\b(cheapest|chepest|cheap|lowest|low|most|expensive|highest|premium|best|"
            r"under|below|less|than|boneless|bbq|barbecue|marinated|marinted|family|bulk)\b",
            " ",
            s,
        )
        s = s.replace("£", " ")
        s = re.sub(r"\s+", " ", s).strip()
        return s

    def _token_tags(self, text: str) -> List[str]:
        t = (text or "").lower()
        t = self._normalize_text(t)
        t = re.sub(r"[^a-z0-9\s_]+", " ", t)
        toks = [x.strip() for x in t.split() if x.strip()]
        out: List[str] = []
        for tok in toks:
            if tok not in out:
                out.append(tok)
        return out

    def _heuristic_plan(self, user_text: str, request_id: str) -> Optional[Dict[str, Any]]:
        """
        Handles:
        - typos: lam, chciken, chepest
        - modifiers: cheapest lamb, lamb under 10, bbq chicken, marinted chicken, boneless lamb
        """
        text = (user_text or "").strip().lower()
        if not text:
            return None
        if len(text.split()) > 7:
            return None

        text_norm = self._normalize_text(text)
        if not text_norm:
            return None

        mods = self._parse_modifiers(text_norm)
        core = self._strip_modifier_words(text_norm) or text_norm

        # Alias core token if needed (helps "chciken" -> "chicken")
        core = self._normalize_text(core)

        # Try fuzzy match to category first
        cat = self._fuzzy_category_match(core, request_id=request_id)

        tags = self._token_tags(core)
        for t in mods.get("tags") or []:
            if t not in tags:
                tags.append(t)

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
                "meta": {
                    "max_items": 12,
                    "search_tags": mods.get("tags") or [],
                    "sort": mods.get("sort"),
                    "max_price": mods.get("max_price"),
                },
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
            "meta": {
                "max_items": 12,
                "search_tags": tags,
                "sort": mods.get("sort"),
                "max_price": mods.get("max_price"),
            },
        }

    def _fuzzy_category_match(self, text: str, request_id: str) -> Optional[str]:
        if not self.catalog:
            self._debug(request_id, "V7.no_catalog_for_category_match")
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

        text_l = self._normalize_text(text).lower().strip()
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

        if (category or product_name) and action in {"", "DO_NOTHING", "STORE_INFO", "FAQ_LOOKUP"}:
            p["action"] = "SEARCH_PRODUCTS"
            if (p.get("intent") or "").strip().lower() in {"", "unknown"}:
                p["intent"] = "browse_category" if category and not product_name else "search_product"

        if len((user_text or "").split()) <= 7 and p.get("needs_clarification"):
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
