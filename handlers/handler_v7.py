# message_handler_v7.py
from __future__ import annotations

from typing import Any, Dict, Optional, List

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

    This is your “feels-like-its-own-LLM” mode.
    """

    def __init__(self, deps: Any):
        # Core deps (all are light wrappers around your JSON + logic)
        self.catalog = getattr(deps, "catalog", None)
        self.policy = getattr(deps, "policy", None)
        self.geo = getattr(deps, "geo", None)
        self.faq = getattr(deps, "faq", None)
        self.overrides = getattr(deps, "overrides", None)
        # optional explicit synonyms dep
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

        # 2) Build dynamic hints from catalog + synonyms
        hints = self._brain_hints()

        # 3) Ask BrainV7 for a plan (intent + action + slots)
        plan = self._safe_plan(user_text=user_text, session=session_snapshot, hints=hints)

        # 4) Execute tools according to the plan (grounding layer)
        facts = self._execute_plan(plan, user_text, session_snapshot)

        # 5) Derive entities from the plan (for session + analytics)
        entities = self._entities_from_plan(plan)

        # 6) Let RendererV7 craft the final reply
        reply_text = self.renderer.render(
            user_text=user_text,
            plan=plan,
            facts=facts,
            session=session_snapshot,
        )

        # 7) Unified payload for the master handler
        return {
            "reply": reply_text,
            "mode": "v7",
            "intent": plan.get("intent"),
            "entities": entities,
            "facts": facts,
        }

    # ------------------------------------------------------------------
    # INTERNAL: BUILD HINTS FOR BRAINV7
    # ------------------------------------------------------------------

    def _brain_hints(self) -> Dict[str, Any]:
        """
        Build the hints dict passed into BrainV7.plan.

        - categories: list[{"id": ..., "name": ...}] from the catalog.
        - category_synonyms: mapping from overrides / synonyms / catalog if available.
        """
        hints: Dict[str, Any] = {}

        # ----- categories from catalog -----
        categories: List[Dict[str, str]] = []

        if self.catalog:
            try:
                raw_cats = None

                # Try common method names first
                if hasattr(self.catalog, "categories") and callable(self.catalog.categories):
                    raw_cats = self.catalog.categories()
                elif hasattr(self.catalog, "all_categories") and callable(self.catalog.all_categories):
                    raw_cats = self.catalog.all_categories()
                elif hasattr(self.catalog, "list_categories") and callable(self.catalog.list_categories):
                    raw_cats = self.catalog.list_categories()
                # Fallback to a data attribute
                elif hasattr(self.catalog, "data"):
                    data = getattr(self.catalog, "data")
                    if isinstance(data, dict):
                        raw_cats = data.get("categories") or data.get("families")

                if raw_cats is None:
                    raw_cats = []

                norm_cats: List[Dict[str, str]] = []
                for c in raw_cats:
                    cid: Optional[str] = None
                    cname: Optional[str] = None

                    if isinstance(c, dict):
                        cid = (
                            str(c.get("id") or c.get("code") or c.get("key") or c.get("slug") or c.get("name") or "")
                            .strip()
                        )
                        cname = str(c.get("name") or c.get("label") or cid).strip()
                    elif isinstance(c, str):
                            cid = c.strip()
                            cname = cid.replace("_", " ").title()
                    else:
                        continue

                    if not cid and not cname:
                        continue

                    norm_cats.append({"id": cid or cname, "name": cname or cid})

                categories = norm_cats

            except Exception as e:
                if self.logger:
                    self.logger.exception("V7: building category hints failed: %s", e)

        hints["categories"] = categories

        # ----- category_synonyms from deps -----
        syn_src = None
        if self.synonyms is not None:
            syn_src = self.synonyms
        elif self.overrides is not None and hasattr(self.overrides, "synonyms"):
            syn_src = getattr(self.overrides, "synonyms")
        elif self.catalog is not None and hasattr(self.catalog, "synonyms"):
            syn_src = getattr(self.catalog, "synonyms")

        if syn_src:
            try:
                # Expecting dict-like mapping
                if isinstance(syn_src, dict):
                    hints["category_synonyms"] = syn_src
                elif hasattr(syn_src, "to_dict"):
                    hints["category_synonyms"] = syn_src.to_dict()
            except Exception as e:
                if self.logger:
                    self.logger.exception("V7: building synonym hints failed: %s", e)

        return hints

    # ------------------------------------------------------------------
    # INTERNAL: BRAIN WRAPPER
    # ------------------------------------------------------------------

    def _safe_plan(self, user_text: str, session: Dict[str, Any], hints: Dict[str, Any]) -> Dict[str, Any]:
        """
        Wrap BrainV7.plan with a hard fallback so a model error
        never crashes the WhatsApp webhook.
        """
        try:
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
                    # Use meta.max_items if present, otherwise default to 8
                    limit = int(meta.get("max_items") or 8)
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
                        meta_info = self.catalog.meta_of(sku)
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

    def _build_search_query(
        self,
        user_text: str,
        category: Optional[str],
        product_name: Optional[str],
        meta: Dict[str, Any],
    ) -> tuple[str, List[str]]:
        """
        Decide what to send to catalog.search as (text, tags).

        - Use Brain meta:
            * meta.search_tags
            * meta.primary_cut
            * meta.search_scope
        - If product_name is present, start from that.
        - If only category is present, use it as both text + tag.
        - If nothing is present, fall back to user_text.
        - For cut-level requests ("wings", "mince"), meta.search_tags
          becomes the "virtual category" built from product data.
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
            human_cat = cat_key.replace("_", " ")
            query = human_cat or cat_key

            if cat_key and cat_key not in tags:
                tags.append(cat_key)

            for token in human_cat.split():
                token = token.strip()
                if token and token not in tags:
                    tags.append(token)

        else:
            query = user_text

        # 3) If we still have no category but do have strong tags,
        #    use them to steer the query as a virtual category.
        if not category and not product_name and tags:
            query = " ".join(tags)

        query = (query or "").strip()
        return query, tags

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
