# ai_modes/renderer_v7.py
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


_CURRENCY_SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€"}
_SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+")
_TONE_STYLES = {"friendly", "professional", "concise"}


class RendererV7:
    """
    V7 renderer: turns plan + facts into the final user-facing message.

    Rules:
    - NO intent detection or slot logic here.
    - ONLY phrasing, grounded on `facts` and `plan`.
    - Optional LLM-based polish via `rewriter`, but it must never invent
      products, prices, or delivery areas that aren't already in `facts`.
    """

    def __init__(
        self,
        rewriter: Optional[Any] = None,
        business_name: str = "",
        *,
        tone_style: str = "friendly",
        max_sentences: int = 2,
    ) -> None:
        # `rewriter` is expected to provide:
        #   rewrite(text, style="sales", facts: dict | None = None, **kwargs)
        self.rewriter = rewriter
        self.business_name = (business_name or "").strip()
        requested_tone = (tone_style or "friendly").strip().lower()
        self.tone_style = requested_tone if requested_tone in _TONE_STYLES else "friendly"
        try:
            configured_max_sentences = int(max_sentences or 2)
        except (TypeError, ValueError):
            configured_max_sentences = 2
        self.max_sentences = min(max(configured_max_sentences, 1), 4)

    # ------------------------------------------------------------------ #
    # PUBLIC ENTRYPOINT                                                  #
    # ------------------------------------------------------------------ #

    def render(
        self,
        *,
        user_text: str,
        plan: Dict[str, Any],
        facts: Dict[str, Any],
        session: Dict[str, Any],
    ) -> str:
        intent = (plan.get("intent") or "unknown").strip()
        action = (plan.get("action") or "").strip().upper()
        needs_clarification = bool(plan.get("needs_clarification", False))
        clarification_question = (plan.get("clarification_question") or "").strip()

        # 1) Brain explicitly asked for a clarifier
        if needs_clarification:
            if clarification_question:
                return clarification_question
            return self._fallback_clarifier(intent, plan, session)

        # 2) Simple / cheap actions that don't depend much on facts
        if action == "GREET" or intent == "greeting":
            base = "Wa alaikum salam! How can I help you today – products, prices, or delivery?"
            return self._polish(base, facts)

        if action == "SMALLTALK_REPLY" or intent == "smalltalk":
            label = self.business_name or "this business"
            base = f"I’m an AI sales assistant for {label}. I can help with products, prices, delivery, and business details."
            return self._polish(base, facts)

        if action == "DO_NOTHING":
            base = (
                "Could you tell me what you’d like help with? "
                "I can help you browse products, compare prices, check delivery, or find a branch."
            )
            return self._polish(base, facts)

        if action == "HUMAN_HANDOFF" or intent == "human_handoff":
            base = (
                "No problem. What’s your postcode so I can find the nearest branch and phone number?"
            )
            return self._polish(base, facts)

        # 3) Data-backed actions
        if action == "SHOW_OFFERS" or intent == "offers":
            msg = self._offers_reply(facts)
            return self._polish(msg, facts)

        if action == "COMPARE_PRODUCTS" or intent == "compare_products":
            msg = self._comparison_reply(facts)
            return self._polish(msg, facts)

        if action == "SHOW_ALTERNATIVES" or intent == "unavailable_product":
            msg = self._alternatives_reply(facts)
            return self._polish(msg, facts)

        if action == "CHECK_DELIVERY" or intent == "check_delivery":
            msg = self._delivery_reply(plan, facts, session)
            return self._polish(msg, facts)

        if action == "SEARCH_PRODUCTS" or intent in {"search_product", "browse_category"}:
            msg = self._products_reply(plan, facts, user_text, session)
            return self._polish(msg, facts)

        if action == "PRICE_CHECK" or intent == "price_check":
            msg = self._price_reply(plan, facts)
            return self._polish(msg, facts)

        if action in {"STORE_INFO", "FAQ_LOOKUP"} or intent in {"store_info", "faq", "unknown"}:
            msg = self._faq_reply(plan, facts, user_text, session)
            return self._polish(msg, facts)

        # 4) Absolute fallback
        base = (
            "I’m not fully sure what you need yet. "
            "Are you looking for a product, price, delivery, or branch information?"
        )
        return self._polish(base, facts)

    # ------------------------------------------------------------------ #
    # DELIVERY                                                           #
    # ------------------------------------------------------------------ #

    def _delivery_reply(
        self,
        plan: Dict[str, Any],
        facts: Dict[str, Any],
        session: Dict[str, Any],
    ) -> str:
        delivery = facts.get("delivery") or {}

        postcode = (
            delivery.get("postcode")
            or plan.get("postcode")
            or session.get("postcode")
        )

        # Nearest branch should be attached regardless of delivery coverage
        nearest = (facts.get("branch") or {}).get("nearest") or {}
        nearest_name = (nearest.get("name") or "").strip()
        nearest_addr = (nearest.get("address") or "").strip()
        nearest_phone = (nearest.get("phone") or "").strip()

        def nearest_suffix() -> str:
            if not nearest_name:
                return ""
            parts: List[str] = [nearest_name]
            if nearest_addr:
                parts.append(nearest_addr)
            if nearest_phone:
                parts.append(f"Call: {nearest_phone}")
            return " Nearest branch: " + " | ".join(parts) + "."

        # If we have no delivery object at all, ask for postcode or show "no info"
        if not delivery:
            if postcode:
                base = (
                    f"I don’t have delivery info for {postcode} yet. "
                    "Could you double-check the postcode or ask about a nearby branch instead?"
                )
                return self._append_cta(base + nearest_suffix())
            return "What’s your postcode (for example: E1 6AN)? I’ll check delivery options for you."

        rule = delivery.get("rule")
        summary = (delivery.get("summary") or "").strip()

        # Covered
        if rule:
            base = f"Yes, we deliver to {postcode}."
            if summary:
                base = f"{base} {summary}"
            return self._append_cta(base + nearest_suffix())

        # Not covered (still show nearest branch if available)
        if postcode:
            base = (
                f"We currently don’t deliver to {postcode}. "
                "You can still visit the nearest branch or call the store for options."
            )
            return self._append_cta(base + nearest_suffix())

        base = (
            "We currently don’t deliver to that area. "
            "You can still visit the nearest branch or call the store for options."
        )
        return self._append_cta(base + nearest_suffix())

    # ------------------------------------------------------------------ #
    # PRODUCTS                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _pretty_category(category: str) -> str:
        return (category or "").replace("_", " ").strip()

    @staticmethod
    def _format_money(value: float, currency: str) -> str:
        code = (currency or "GBP").upper()
        symbol = _CURRENCY_SYMBOLS.get(code)
        return f"{symbol}{value:.2f}" if symbol else f"{code} {value:.2f}"

    def _format_item_line(self, item: Dict[str, Any], currency: str) -> str:
        name = item.get("name") or item.get("_norm_name") or ""
        name = name.strip()
        if not name:
            return ""

        unit = (item.get("unit") or "").strip()
        price = item.get("price")
        bits: List[str] = [name]

        if unit and unit.lower() not in name.lower():
            bits[-1] = f"{name} ({unit})"

        if isinstance(price, (int, float)):
            bits.append(self._format_money(float(price), currency))

        return " – ".join(bits)

    def _products_reply(
        self,
        plan: Dict[str, Any],
        facts: Dict[str, Any],
        user_text: str,
        session: Dict[str, Any],
    ) -> str:
        items = facts.get("items") or []
        raw_category = plan.get("category") or session.get("last_category") or ""
        category = self._pretty_category(raw_category)
        product_name = (plan.get("product_name") or "").strip()
        currency = str(facts.get("currency") or "GBP")

        user_text_raw = (user_text or "").strip()
        user_text_lower = user_text_raw.lower()

        search_meta = facts.get("search_meta") or {}
        scope = search_meta.get("scope", "top_picks")
        item_level = bool(search_meta.get("item_level", False))
        primary_cut = search_meta.get("primary_cut")

        try:
            max_items = int(search_meta.get("max_items", 8))
        except Exception:
            max_items = 8

        wants_chunking = bool(search_meta.get("wants_chunking", False))

        if not items:
            keywords = ("full", "all", "everything", "entire", "whole")
            pn_lower = (product_name or "").lower()

            if any(k in user_text_lower for k in keywords) or any(k in pn_lower for k in keywords):
                if category:
                    return (
                        f"The {category} catalog is quite big. "
                        "Tell me the product type, category, or feature you need."
                    )
                return (
                    "The full catalog is very large. "
                    "Tell me the product type, category, or feature you need."
                )

            if product_name:
                return f"I couldn’t find matches for “{product_name}”. Could you try a different product name, category, or feature?"
            if category:
                return f"I couldn’t find matches in {category}. Could you try a different product or category?"
            return "I couldn’t find matching items. What product, category, or feature are you looking for?"

        total_items = len(items)

        if scope == "item_list":
            limit = min(total_items, max(4, min(max_items, 10)))
        elif scope in {"full_category", "full_store"}:
            limit = min(total_items, max(10, min(max_items, 20)))
        else:
            limit = min(total_items, max(4, min(max_items, 8)))

        top = items[:limit]

        lines: List[str] = []
        for idx, item in enumerate(top, start=1):
            line = self._format_item_line(item, currency)
            if line:
                lines.append(f"{idx}) {line}")

        if not lines:
            return "I found some items, but I couldn’t read their names. Could you try describing the product again?"

        if item_level and primary_cut:
            intro = f"Here are our {primary_cut} options" + (f" in {category}:" if category else ":")
        elif scope == "full_category" and category:
            intro = f"Here’s a wider selection from our {category} range:"
        elif scope == "full_store":
            intro = "Here’s a wider selection from across the store:"
        elif category:
            intro = f"For {category}, here are some good options:"
        else:
            intro = "Here are some good options I found:"

        body = " ".join(lines)

        extra_tail = ""
        if total_items > limit:
            if scope in {"full_category", "full_store"} or wants_chunking:
                extra_tail = (
                    f" I’ve shown the first {limit} items to keep things clear. "
                    "Tell me a product type, category, feature, or a number from the list."
                )
            elif item_level:
                extra_tail = (
                    f" I’ve shown the main {primary_cut} options. "
                    "If you want something more specific, tell me the number you like."
                )

        followup = " Tell me the number you like and I can give you prices or more options."
        base = f"{intro} {body}{extra_tail}{followup}"
        return self._append_cta(base)

    # ------------------------------------------------------------------ #
    # PRICE                                                              #
    # ------------------------------------------------------------------ #

    def _comparison_reply(self, facts: Dict[str, Any]) -> str:
        comparison = facts.get("comparison") or {}
        items = comparison.get("items") if isinstance(comparison, dict) else []
        if not isinstance(items, list) or len(items) != 2:
            return "Tell me the two product names you’d like to compare."

        currency = str(facts.get("currency") or "GBP")
        lines: List[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("_norm_name") or "").strip()
            price = item.get("price")
            stock = "in stock" if item.get("in_stock", True) else "out of stock"
            if not name or not isinstance(price, (int, float)):
                continue
            lines.append(f"{name}: {self._format_money(float(price), currency)}, {stock}.")

        if len(lines) != 2:
            return "I found the products, but I could not confirm both prices."
        return " ".join(lines)

    def _alternatives_reply(self, facts: Dict[str, Any]) -> str:
        unavailable = facts.get("unavailable_product") or {}
        name = str(unavailable.get("name") or unavailable.get("_norm_name") or "That product").strip()
        alternatives = facts.get("items") or []
        currency = str(facts.get("currency") or "GBP")

        if not isinstance(alternatives, list) or not alternatives:
            return f"{name} is currently out of stock. I do not have a similar in-stock option recorded right now."

        lines: List[str] = []
        for item in alternatives[:3]:
            if not isinstance(item, dict):
                continue
            line = self._format_item_line(item, currency)
            if line:
                lines.append(line)

        if not lines:
            return f"{name} is currently out of stock. I do not have a similar in-stock option recorded right now."
        return f"{name} is currently out of stock. Available alternatives: " + " | ".join(lines) + "."

    def _price_reply(self, plan: Dict[str, Any], facts: Dict[str, Any]) -> str:
        price_block = facts.get("price") or {}
        sku = price_block.get("sku") or plan.get("sku")

        if not sku:
            return "Tell me the SKU or exact product name and I’ll confirm the price for you."

        price = price_block.get("price", None)
        in_stock = price_block.get("in_stock", None)
        name = (price_block.get("name") or "").strip()
        unit = (price_block.get("unit") or "").strip()
        currency = str(facts.get("currency") or "GBP")

        if price is None:
            return f"I couldn’t find a price for {sku}. It might be missing or not available right now."

        stock_str = "in stock" if in_stock else "out of stock"
        label = name or sku
        if unit:
            label = f"{label} ({unit})"

        base = f"{label} is {self._format_money(float(price), currency)} and {stock_str}."
        return self._append_cta(base)

    # ------------------------------------------------------------------ #
    # OFFERS                                                             #
    # ------------------------------------------------------------------ #

    def _offers_reply(self, facts: Dict[str, Any]) -> str:
        offer_data = facts.get("offers") or {}
        offers = offer_data.get("items") if isinstance(offer_data, dict) else []
        product_name = str(offer_data.get("matched_product_name") or "").strip() if isinstance(offer_data, dict) else ""

        if not isinstance(offers, list) or not offers:
            if product_name:
                return f"I do not have a current offer recorded for {product_name}."
            return "There are no current offers configured at the moment."

        lines: List[str] = []
        for offer in offers[:3]:
            if not isinstance(offer, dict):
                continue
            title = str(offer.get("title") or "").strip()
            description = str(offer.get("description") or "").strip()
            if not title or not description:
                continue
            # Keep terms, code, and expiry in one sentence so a tenant's
            # configured reply-length setting cannot hide a material condition.
            description = re.sub(r"[.!?]+", ",", description).strip(" ,")
            detail = f"{title}: {description}"
            code = str(offer.get("code") or "").strip()
            ends_on = str(offer.get("ends_on") or "").strip()
            if code:
                detail = f"{detail} (code: {code})"
            if ends_on:
                detail = f"{detail} (ends {ends_on})"
            lines.append(detail)

        if not lines:
            return "There are no current offers configured at the moment."
        lead = f"For {product_name}, the current offer is" if product_name else "Current offers"
        return f"{lead}: " + " | ".join(lines) + "."

    # ------------------------------------------------------------------ #
    # FAQ / STORE INFO                                                   #
    # ------------------------------------------------------------------ #

    def _faq_reply(
        self,
        plan: Dict[str, Any],
        facts: Dict[str, Any],
        user_text: str,
        session: Dict[str, Any],
    ) -> str:
        faq = facts.get("faq") or {}
        answer = (faq.get("answer") or "").strip()
        store_info = facts.get("store_info") or {}
        store_answer = (store_info.get("answer") or "").strip()

        if answer:
            return self._append_cta(answer)
        if store_answer:
            return self._append_cta(store_answer)

        delivery = facts.get("delivery") or {}
        postcode = (
            delivery.get("postcode")
            or plan.get("postcode")
            or session.get("postcode")
        )
        summary = (delivery.get("summary") or "").strip()

        if postcode and summary:
            return self._append_cta(f"For {postcode}: {summary}")

        return (
            "I’m not fully sure about that from my data. "
            "You can ask about products, prices, delivery, or store branches."
        )

    # ------------------------------------------------------------------ #
    # CLARIFIERS                                                         #
    # ------------------------------------------------------------------ #

    def _fallback_clarifier(
        self,
        intent: str,
        plan: Dict[str, Any],
        session: Dict[str, Any],
    ) -> str:
        intent = (intent or "unknown").strip()

        if intent == "check_delivery":
            return "What’s your postcode (for example: E1 6AN)?"

        if intent in {"search_product", "browse_category"}:
            return "What product, category, or feature are you looking for?"

        if intent == "price_check":
            return "Which product or SKU should I check the price for?"

        if intent == "human_handoff":
            return "What’s your postcode so I can find the nearest branch and number?"

        return "Could you clarify what you need? For example: a product, delivery, or opening times."

    # ------------------------------------------------------------------ #
    # POLISH / CTA                                                       #
    # ------------------------------------------------------------------ #

    def _append_cta(self, text: str) -> str:
        t = (text or "").strip()
        if not t:
            return t

        lower = t.lower()
        if lower.endswith(("anything else?", "anything else.", "anything else")):
            return t
        if t.endswith("?"):
            return t

        return t

    def _polish(self, text: str, facts: Dict[str, Any]) -> str:
        text = (text or "").strip()
        if not text:
            return ""

        rewritten = text
        if self.rewriter:
            try:
                rewritten = self.rewriter.rewrite(rewritten, style=self.tone_style, facts=facts)
            except Exception:
                rewritten = text

        if self.tone_style == "professional":
            rewritten = re.sub(r"\bI['’]m\b", "I am", rewritten)
            rewritten = re.sub(r"\bwe['’]re\b", "we are", rewritten, flags=re.IGNORECASE)
            rewritten = re.sub(r"\bdon['’]t\b", "do not", rewritten, flags=re.IGNORECASE)

        sentences = [part.strip() for part in _SENTENCE_BREAK_RE.split(rewritten) if part.strip()]
        return " ".join(sentences[: self.max_sentences]).strip()
