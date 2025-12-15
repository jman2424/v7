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
    V7 handler (patched):
    - Adds strong logging with request_id correlation
    - Adds heuristic resolver for short prompts + typos
    - Forces catalog.search when user likely asked for products
    - Always returns ui.catalog_items for webchat
    """

    def __init__(self, deps: Any):
        self.catalog = getattr(deps, "catalog", None)
        self.policy = getattr(deps, "policy", None)
        self.geo = getattr(deps, "geo", None)
        self.faq = getattr(deps, "faq", None)
        self.overrides = getattr(deps, "overrides", None)
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

        request_id = self._ctx_rid(ctx) or str(uuid.uuid4())[:12]
        channel = getattr(ctx, "channel", None) or "unknown"
        tenant = getattr(ctx, "tenant", None) or "unknown"
        session_id = getattr(ctx, "session_id", None) or "unknown"

        session_snapshot = {
            "postcode": sess.get("postcode"),
            "last_intent": sess.get("last_intent"),
            "last_category": sess.get("last_category"),
            "last_sku": sess.get("last_sku"),
        }

        self._info(request_id, "V7.start", tenant=tenant, session=session_id, channel=channel, text=self._clip(user_text, 200), sess=session_snapshot)

        # 1) Heuristic pre-pass: short prompts + typos should still return products
        heuristic_plan = self._heuristic_plan(user_text, request_id=request_id)

        if heuristic_plan:
            self._info(request_id, "V7.heuristic_used", plan=self._safe_plan_log(heuristic_plan))
            plan = heuristic_plan
        else:
            # 2) Brain plan
            plan = self._safe_plan(user_text=user_text, session=session_snapshot, request_id=request_id)
            self._debug(request_id, "V7.plan_raw", plan=self._safe_plan_log(plan))

            # 3) Normalize plan (if brain gave weak action for recognized slot)
            plan = self._normalize_plan(plan, user_text)
            self._debug(request_id, "V7.plan_norm", plan=self._safe_plan_log(plan))

        # 4) Execute
        facts = self._execute_plan(plan, user_text, session_snapshot, request_id=request_id)

        # 5) Entities
        entities = self._entities_from_plan(plan)

        # 6) Render
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
            entities=entities,
            facts_keys=list(facts.keys()),
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

    # ------------------------------------------------------------------
    # HEURISTIC PLANNING (THE PATCH THAT FIXES YOUR ISSUE)
    # ------------------------------------------------------------------

    def _heuristic_plan(self, user_text: str, request_id: str) -> Optional[Dict[str, Any]]:
        """
        If user gives a short prompt (<= 2 words), don't rely on Brain.
        - Fix typos by fuzzy matching categories
        - Otherwise treat as product query/tag (e.g. "wings")
        """
        text = (user_text or "").strip().lower()
        if not text:
            return None

        # Only for short prompts (your failing cases)
        if len(text.split()) > 2:
            return None

        # Quick normalize
        text_norm = re.sub(r"[^a-z0-9\s_]+", "", text).strip()

        # 1) Try fuzzy match to categories
        cat = self._fuzzy_category_match(text_norm, request_id=request_id)
        if cat:
            return {
                "intent": "browse_category",
                "action": "SEARCH_PRODUCTS",
                "category": cat,
                "product_name": None,
                "postcode": None,
                "sku": None,
                "needs_clarification": False,
                "clarification_question": "",
                "meta": {"max_items": 8},
            }

        # 2) If not a category, treat it as a product tag/query
        # This covers: wings, chops, mince, thighs, breast, ribs, etc.
        return {
            "intent": "search_product",
            "action": "SEARCH_PRODUCTS",
            "category": None,
            "product_name": text_norm,
            "postcode": None,
            "sku": None,
            "needs_clarification": False,
            "clarification_question": "",
            "meta": {"max_items": 8, "search_tags": [text_norm]},
        }

    def _fuzzy_category_match(self, text: str, request_id: str) -> Optional[str]:
        """
        Match user text to known catalog categories (id/name) using difflib.
        Handles typos like 'chciken' -> 'chicken' if chicken is a category.
        """
        if not self.catalog:
            return None

        try:
            cats = self.catalog.categories() or []
        except Exception as e:
            self._exc(request_id, "V7.categories_failed", err=str(e))
            return None

        # Build candidates from ids + names
        candidates: List[str] = []
        id_map: Dict[str, str] = {}

        for c in cats:
            if not isinstance(c, dict):
                continue
            cid = (c.get("id") or "").strip()
            nm = (c.get("name") or "").strip()
            if cid:
                key = cid.lower()
                candidates.append(key)
                id_map[key] = cid
            if nm:
                key = nm.lower()
                candidates.append(key)
                # if name matches, still return id if possible
                if cid:
                    id_map[key] = cid
                else:
                    id_map[key] = nm  # fallback to name

        if not candidates:
            return None

        # direct match
        if text in id_map:
            return id_map[text]

        # fuzzy
        match = difflib.get_close_matches(text, candidates, n=1, cutoff=0.78)
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

            return self.brain.plan(
                user_text=user_text,
                session=session,
                history=[],
                hints=hints,
            )
        except Exception as e:
            self._exc(request_id, "V7.brain_plan_failed", err=str(e))
            return {
                "intent": "unknown",
                "action": "DO_NOTHING",
                "category": None,
                "product_name": None,
                "postcode": session.get("postcode"),
                "sku": session.get("last_sku"),
                "handoff_channel": None,
                "needs_clarification": False,
                "clarification_question": "",
                "meta": {"max_items": 8},
            }

    def _normalize_plan(self, plan: Dict[str, Any], user_text: str) -> Dict[str, Any]:
        p = dict(plan or {})
        action = (p.get("action") or "").strip().upper()

        category = p.get("category")
        product_name = p.get("product_name")

        # If brain found category/product but didn't choose search -> force search
        if (category or product_name) and action in {"", "DO_NOTHING", "STORE_INFO", "FAQ_LOOKUP"}:
            p["action"] = "SEARCH_PRODUCTS"
            if (p.get("intent") or "").strip().lower() in {"", "unknown"}:
                p["intent"] = "browse_category" if category and not product_name else "search_product"

        # If short prompt and brain tries to clarify, don't block results
        if len((user_text or "").split()) <= 2 and p.get("needs_clarification"):
            p["needs_clarification"] = False
            p["clarification_question"] = ""

        meta = p.get("meta") or {}
        if not isinstance(meta, dict):
            meta = {}
        meta.setdefault("max_items", 8)
        p["meta"] = meta
        return p

    # ------------------------------------------------------------------
    # EXECUTION (catalog / delivery / faq)
    # ------------------------------------------------------------------

    def _execute_plan(self, plan: Dict[str, Any], user_text: str, session: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        action = (plan.get("action") or "DO_NOTHING").strip().upper()
        intent = (plan.get("intent") or "unknown").strip()
        meta = plan.get("meta") or {}
        facts: Dict[str, Any] = {}

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

        # PRODUCT SEARCH
        if action == "SEARCH_PRODUCTS" or intent in {"search_product", "browse_category"}:
            query, tags = self._build_search_query(user_text, category, product_name, meta)

            try:
                limit = int((meta or {}).get("max_items") or 8)
            except Exception:
                limit = 8

            self._info(request_id, "V7.catalog.search", query=self._clip(query, 120), tags=(tags or [])[:20], limit=limit)

            if self.catalog and (query or tags):
                try:
                    items = self.catalog.search(text=query, tags=tags, limit=limit)
                except Exception as e:
                    self._exc(request_id, "V7.catalog.search_failed", err=str(e))
                    items = []
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
