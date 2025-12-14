# handlers/message_handler_v7.py
from __future__ import annotations

import re
from typing import Any, Dict, Optional, List, Tuple

from brain_v7 import BrainV7
from renderer_v7 import RendererV7


class MessageHandlerV7:
    """
    V7: AI-first handler using BrainV7 + RendererV7.

    Flow:
      1) Build a session snapshot for the brain.
      2) BrainV7.plan(...) -> JSON plan (intent, action, slots, flags).
      3) Execute tools (catalog / delivery / faq) based on the plan.
      4) RendererV7.render(...) -> final reply text in store’s voice.
      5) Return unified payload for master handler (reply, intent, entities, facts).
    """

    def __init__(self, deps: Any):
        # Core deps (all are light wrappers around your JSON + logic)
        self.catalog = getattr(deps, "catalog", None)
        self.policy = getattr(deps, "policy", None)
        self.geo = getattr(deps, "geo", None)
        self.faq = getattr(deps, "faq", None)
        self.overrides = getattr(deps, "overrides", None)
        self.synonyms = getattr(deps, "synonyms", None)

        # Optional extras
        self.logger = getattr(deps, "logger", None)

        # Brain + renderer
        self.brain = BrainV7(getattr(deps, "openai_client", None))
        self.renderer = RendererV7(getattr(deps, "rewriter", None))

    # ------------------------------------------------------------------
    # PUBLIC ENTRYPOINT (called by master MessageHandler)
    # ------------------------------------------------------------------

    def handle(self, user_text: str, ctx: Dict[str, Any], sess: Dict[str, Any]) -> Dict[str, Any]:
        user_text = (user_text or "").strip()

        # 1) Build session snapshot for BrainV7
        session_snapshot = {
            "postcode": sess.get("postcode"),
            "last_intent": sess.get("last_intent"),
            "last_category": sess.get("last_category"),
            "last_sku": sess.get("last_sku"),
        }

        # 2) Ask BrainV7 for a plan (intent + action + slots)
        plan = self._safe_plan(user_text=user_text, session=session_snapshot)

        # ✅ Normalize plan so webchat gets items instead of looping on clarification
        plan = self._normalize_plan(plan=plan, user_text=user_text)

        # 3) Execute tools according to the plan (grounding layer)
        facts = self._execute_plan(plan, user_text, session_snapshot)

        # 4) Derive entities from the plan (for session + analytics)
        entities = self._entities_from_plan(plan)

        # 5) Let RendererV7 craft the final reply
        reply_text = self.renderer.render(
            user_text=user_text,
            plan=plan,
            facts=facts,
            session=session_snapshot,
        )

        # ✅ UI payload for webchat (cards/list)
        ui = {
            "has_catalog": bool(facts.get("items")),
            "catalog_items": self._format_items_for_ui(facts.get("items") or []),
        }

        # 6) Unified payload for the master handler
        return {
            "reply": reply_text,
            "mode": "v7",
            "intent": plan.get("intent"),
            "entities": entities,
            "facts": facts,
            "ui": ui,  # ✅ webchat should render ui.catalog_items
        }

    # ------------------------------------------------------------------
    # INTERNAL: BRAIN WRAPPER
    # ------------------------------------------------------------------

    def _safe_plan(self, user_text: str, session: Dict[str, Any]) -> Dict[str, Any]:
        """
        Wrap BrainV7.plan with a hard fallback so a model error
        never crashes the WhatsApp webhook.
        Also passes live categories + synonyms as hints so the model
        can align with whatever is in catalog.json.
        """
        try:
            hints: Dict[str, Any] = {}

            if self.catalog:
                try:
                    cats = self.catalog.categories()
                    hints["categories"] = [
                        {"id": c.get("id"), "name": c.get("name")}
                        for c in (cats or [])
                        if c.get("id") and c.get("name")
                    ]
                except Exception as e:
                    if self.logger:
                        self.logger.exception("V7: failed to load categories for hints: %s", e)

            if self.synonyms:
                hints["synonyms"] = self.synonyms

            return self.brain.plan(
                user_text=user_text,
                session=session,
                history=[],  # can plug recent turns here later
                hints=hints,
            )
        except Exception as e:
            if self.logger:
                self.logger.exception("V7: Brain plan failed: %s", e)

            # Minimal safe fallback
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
                "meta": {"is_greeting": False, "is_goodbye": False},
            }

    # ------------------------------------------------------------------
    # ✅ INTERNAL: PLAN NORMALIZER (stops clarify loops; forces browse/search)
    # ------------------------------------------------------------------

    def _normalize_plan(self, plan: Dict[str, Any], user_text: str) -> Dict[str, Any]:
        """
        If the model already identified a category/product, don't block with
        clarification/weak action. Force a catalog search so the UI receives items.
        """
        p = dict(plan or {})
        action = (p.get("action") or "").strip().upper()
        intent = (p.get("intent") or "").strip().lower()

        category = p.get("category")
        product_name = p.get("product_name")

        has_signal = bool(category or product_name)

        # If brain recognized something but chose a non-catalog action, force search
        if has_signal and action in {"", "DO_NOTHING", "STORE_INFO", "FAQ_LOOKUP"}:
            p["action"] = "SEARCH_PRODUCTS"
            if intent in {"", "unknown"}:
                p["intent"] = "browse_category" if category and not product_name else "search_product"

        # If category is clear, don't demand clarification
        if category and p.get("needs_clarification"):
            p["needs_clarification"] = False
            p["clarification_question"] = ""

        # Ensure meta exists and default max_items
        meta = p.get("meta") or {}
        if not isinstance(meta, dict):
            meta = {}
        meta.setdefault("max_items", 8)
        p["meta"] = meta

        return p

    # ------------------------------------------------------------------
    # INTERNAL: TOOL EXECUTION LAYER
    # ------------------------------------------------------------------

    def _execute_plan(
        self,
        plan: Dict[str, Any],
        user_text: str,
        session: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Runs the actual tools (catalog, delivery, faq, etc.) for the chosen action.
        This is where you ground the brain’s plan in real store data.
        """
        action = (plan.get("action") or "DO_NOTHING").strip().upper()
        intent = (plan.get("intent") or "unknown").strip()
        meta = plan.get("meta") or {}
        facts: Dict[str, Any] = {}

        category = plan.get("category")
        product_name = plan.get("product_name") or None
        postcode = plan.get("postcode") or session.get("postcode")
        sku = plan.get("sku")

        # --- DELIVERY CHECK ---
        if action == "CHECK_DELIVERY" or intent == "check_delivery":
            if self.policy and postcode:
                try:
                    rule = self.policy.delivery_rule_for(postcode)
                    summary = self.policy.delivery_summary(postcode)
                except Exception as e:
                    if self.logger:
                        self.logger.exception("V7: delivery lookup failed: %s", e)
                    rule, summary = None, ""
                facts["delivery"] = {
                    "postcode": postcode,
                    "rule": rule,
                    "summary": summary or "",
                }

            if self.geo and postcode:
                try:
                    nb = self.geo.nearest_for_postcode(postcode)
                except Exception as e:
                    if self.logger:
                        self.logger.exception("V7: geo lookup failed: %s", e)
                    nb = None
                if nb:
                    facts.setdefault("branch", {})["nearest"] = nb

        # --- PRODUCT SEARCH ---
        if action == "SEARCH_PRODUCTS" or intent in {"search_product", "browse_category"}:
            query, tags = self._build_search_query(
                user_text=user_text,
                category=category,
                product_name=product_name,
                meta=meta,
            )

            if self.logger:
                self.logger.info(
                    "V7: catalog.search action=%s intent=%s query=%r tags=%r category=%r product_name=%r meta=%r",
                    action,
                    intent,
                    query,
                    tags,
                    category,
                    product_name,
                    meta,
                )

            if self.catalog and (query or tags):
                try:
                    limit = int((meta or {}).get("max_items") or 8)
                except Exception:
                    limit = 8

                try:
                    items = self.catalog.search(text=query, tags=tags, limit=limit)
                except Exception as e:
                    if self.logger:
                        self.logger.exception("V7: catalog.search failed: %s", e)
                    items = []

                facts["items"] = items

        # --- PRICE CHECK ---
        if action == "PRICE_CHECK" or intent == "price_check":
            if self.catalog and sku:
                try:
                    price_val = self.catalog.price_of(sku)
                    in_stock = self.catalog.in_stock(sku)
                    try:
                        meta_info = self.catalog.meta_of(sku)  # if you have this helper
                    except Exception:
                        meta_info = {}
                except Exception as e:
                    if self.logger:
                        self.logger.exception("V7: price check failed: %s", e)
                    price_val, in_stock, meta_info = None, None, {}
                facts["price"] = {
                    "sku": sku,
                    "price": price_val,
                    "in_stock": in_stock,
                    "name": meta_info.get("name"),
                    "unit": meta_info.get("unit"),
                }

        # --- STORE / FAQ LOOKUP ---
        if action in {"STORE_INFO", "FAQ_LOOKUP"} or intent in {"store_info", "faq", "unknown"}:
            if self.faq:
                try:
                    m = self.faq.best_match(user_text, hint_tags=None, top_k=1)
                except Exception as e:
                    if self.logger:
                        self.logger.exception("V7: faq.best_match failed: %s", e)
                    m = None

                if m:
                    entry = m[0]
                    placeholders: Dict[str, Any] = {}
                    if postcode and self.policy:
                        placeholders["postcode"] = postcode
                        try:
                            placeholders["delivery_summary"] = (
                                self.policy.delivery_summary(postcode) or ""
                            )
                        except Exception:
                            placeholders["delivery_summary"] = ""

                    if session.get("nearest_branch_id") and facts.get("branch", {}).get("nearest"):
                        placeholders["branch_name"] = (
                            facts["branch"]["nearest"].get("name") or ""
                        )

                    try:
                        answer = self.faq.render_answer(entry, placeholders)
                    except Exception as e:
                        if self.logger:
                            self.logger.exception("V7: faq.render_answer failed: %s", e)
                        answer = ""

                    facts["faq"] = {
                        "entry": entry,
                        "answer": answer,
                    }

        # SMALLTALK, GREET, HUMAN_HANDOFF, DO_NOTHING don't need facts by default
        return facts

    # ------------------------------------------------------------------
    # INTERNAL: SEARCH QUERY BUILDER
    # ------------------------------------------------------------------

    @staticmethod
    def _slug_key(s: str) -> str:
        s = (s or "").lower()
        s = re.sub(r"[^a-z0-9]+", "_", s)
        s = re.sub(r"_+", "_", s)
        return s.strip("_")

    def _build_search_query(
        self,
        user_text: str,
        category: Optional[str],
        product_name: Optional[str],
        meta: Dict[str, Any],
    ) -> Tuple[str, List[str]]:
        """
        Decide what to send to catalog.search as (text, tags).

        - Uses Brain meta:
            * meta.search_tags
            * meta.primary_cut
            * meta.search_scope
        - If product_name is present, start from that.
        - If only category is present, use it as both text + multiple tags.
        - If nothing is present, fall back to user_text.
        """
        tags: List[str] = []
        query = ""

        meta = meta or {}

        # 1) Seed tags from meta.search_tags / primary_cut
        meta_tags = meta.get("search_tags") or []
        if isinstance(meta_tags, str):
            meta_tags = [meta_tags]

        for t in meta_tags:
            t = str(t).strip().lower()
            if t and t not in tags:
                tags.append(t)

        primary_cut = meta.get("primary_cut")
        if primary_cut:
            primary_cut = str(primary_cut).strip().lower()
            if primary_cut and primary_cut not in tags:
                tags.append(primary_cut)

        # 2) Main text query
        if product_name:
            query = str(product_name).strip()

        elif category:
            cat_key = str(category).strip().lower()
            slug_cat = self._slug_key(cat_key)
            human_cat = cat_key.replace("_", " ")
            query = human_cat or slug_cat

            for t in {cat_key, slug_cat}:
                if t and t not in tags:
                    tags.append(t)

            for token in re.split(r"[ _]+", slug_cat):
                token = token.strip()
                if token and token not in tags:
                    tags.append(token)

        else:
            query = user_text

        # 3) If we still have no category and no product_name but do have tags,
        #    treat tags as a virtual query (e.g. ["wings"] -> "wings").
        if not category and not product_name and tags:
            query = " ".join(tags)

        query = (query or "").strip()
        return query, tags

    # ------------------------------------------------------------------
    # ✅ INTERNAL: UI FORMATTER (stable payload for webchat)
    # ------------------------------------------------------------------

    def _format_items_for_ui(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Convert whatever catalog.search returns into a stable shape for webchat.
        Frontend should render response.ui.catalog_items.
        """
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
                else:
                    in_stock = None

            out.append(
                {
                    "sku": sku,
                    "name": name,
                    "price": price,
                    "unit": unit,
                    "in_stock": in_stock,  # bool | None
                    "tags": it.get("tags") or [],
                    "category": it.get("category") or it.get("category_id"),
                    "url": it.get("url") or it.get("link"),
                    "image": it.get("image") or it.get("image_url"),
                    "raw": it,  # keep raw for debugging
                }
            )
        return out

    # ------------------------------------------------------------------
    # INTERNAL: ENTITY MAPPING
    # ------------------------------------------------------------------

    def _entities_from_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map BrainV7 slots into the 'entities' payload that the master handler
        will use for session saving and analytics.
        """
        entities: Dict[str, Any] = {}

        cat = plan.get("category")
        if cat:
            entities["category"] = cat

        postcode = plan.get("postcode")
        if postcode:
            entities["postcode"] = postcode

        sku = plan.get("sku")
        if sku:
            entities["sku"] = sku

        product_name = plan.get("product_name")
        if product_name:
            entities["product_name"] = product_name

        handoff_channel = plan.get("handoff_channel")
        if handoff_channel:
            entities["handoff_channel"] = handoff_channel

        return entities
