"""
Message orchestrator:
- Accepts user message + context
- Routes to intents, gathers facts
- Executes mode (V5/V6/V7) planning/tool-use if available
- Rewrites for tone
- Logs analytics, updates CRM
- Returns reply payload (string + meta)

No external I/O here; all connectors run in routes or services.* layers.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

from . import HandlerDeps, DEFAULT_SESSION_TTL


@dataclass
class MessageContext:
    tenant: str
    session_id: str
    channel: str  # "web" | "whatsapp" | "api"
    metadata: Dict[str, Any]


class MessageHandler:
    def __init__(self, deps: HandlerDeps):
        self.mode = deps.mode
        self.rewriter = deps.rewriter
        self.analytics = deps.analytics
        self.crm = deps.crm
        self.memory = deps.memory
        self.router = deps.router
        self.catalog = deps.catalog
        self.policy = deps.policy
        self.geo = deps.geo
        self.faq = deps.faq
        self.synonyms = deps.synonyms
        self.overrides = deps.overrides

    # ---- public entrypoint ----

    def handle(
        self,
        user_text: str,
        *,
        tenant: str,
        session_id: str,
        channel: str = "web",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ctx = MessageContext(
            tenant=tenant, session_id=session_id, channel=channel, metadata=metadata or {}
        )

        # 1) Normalize & read session state
        user_text = (user_text or "").strip()
        sess = self._load_session(ctx)

        # 2) Route (intent, entities, clarifiers)
        route = self.router.route(user_text, self._ctx_for_router(ctx, sess))

        # 3) If clarifier required, produce minimal, accurate question
        if route.get("needs_clarification"):
            reply = route["clarifier"]
            self._post_analytics(ctx, user_text, reply, route, mode=self.mode.name(), ok=True)
            return self._make_reply(reply, ctx, route, mode=self.mode.name())

        # 4) Gather facts (retrieval/tool calls)
        facts = self._gather_facts(route, ctx, sess)

        # 5) Compose deterministic draft (short, factual)
        draft = self._compose_draft(route, facts, ctx)

        # 6) AI rewrite (V6/V7) if enabled; tone guardrails
        try:
            final = self.mode.rewrite(draft, ctx=self._ctx_for_mode(ctx, sess, route, facts))
        except Exception:
            # fallback: deterministic draft
            final = self.rewriter.rewrite(draft, style="safe")

        # 7) Persist session deltas (postcode, nearest_branch_id, last intents)
        self._save_session(ctx, sess, route, facts)

        # 8) CRM + analytics
        self._update_crm(ctx, user_text, final, route, facts)
        self._post_analytics(ctx, user_text, final, route, mode=self.mode.name(), ok=True)

        # 9) Done
        return self._make_reply(final, ctx, route, mode=self.mode.name(), facts=facts)

    # ---- helpers ----

    def _ctx_for_router(self, ctx: MessageContext, sess: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "tenant": ctx.tenant,
            "channel": ctx.channel,
            "session": {
                "postcode": sess.get("postcode"),
                "nearest_branch_id": sess.get("nearest_branch_id"),
                "last_category": sess.get("last_category"),
                "last_sku": sess.get("last_sku"),
            },
            "coverage_prefixes": getattr(self.geo, "coverage_prefixes", lambda: [])(),
        }

    def _ctx_for_mode(
        self,
        ctx: MessageContext,
        sess: Dict[str, Any],
        route: Dict[str, Any],
        facts: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "tenant": ctx.tenant,
            "channel": ctx.channel,
            "intent": route.get("intent"),
            "entities": route.get("entities", {}),
            "facts": facts,
            "policy": {
                "click_and_collect": self.policy.click_and_collect(),
            },
            "session": sess,
            "style": {
                "concise": self.overrides.get_bool("tone.concise", True),
            },
        }

    def _gather_facts(self, route: Dict[str, Any], ctx: MessageContext, sess: Dict[str, Any]) -> Dict[str, Any]:
        intent = route.get("intent")
        ent = route.get("entities", {})
        facts: Dict[str, Any] = {}

        # Delivery check
        if intent in {"check_delivery", "ask_postcode"} or ("postcode" in ent):
            pc = ent.get("postcode") or sess.get("postcode")
            if pc:
                rule = self.policy.delivery_rule_for(pc)
                facts["delivery"] = {"postcode": pc, "rule": rule, "summary": self.policy.delivery_summary(pc)}
                # branch
                nb = self.geo.nearest_for_postcode(pc)
                if nb:
                    facts["branch"] = {"nearest": nb}

        # Product search
        if intent in {"search_product", "browse_category"}:
            query = ent.get("query")
            tags = ent.get("tags") or []
            if query or tags:
                items = self.catalog.search(text=query, tags=tags, limit=6)
                facts["items"] = items

        # Price lookup
        if intent == "price_check" and ent.get("sku"):
            sku = ent["sku"]
            facts["price"] = {"sku": sku, "price": self.catalog.price_of(sku), "in_stock": self.catalog.in_stock(sku)}

        # FAQ fallback
        if intent in {"faq", "unknown"}:
            hints = ent.get("tags") or []
            m = self.faq.best_match(route.get("utterance", ""), hint_tags=hints, top_k=1)
            if m:
                placeholders = {}
                if sess.get("postcode"):
                    placeholders["postcode"] = sess["postcode"]
                    placeholders["delivery_summary"] = self.policy.delivery_summary(sess["postcode"]) or ""
                if sess.get("nearest_branch_id") and facts.get("branch", {}).get("nearest"):
                    placeholders["branch_name"] = facts["branch"]["nearest"].get("name") or ""
                facts["faq"] = {"entry": m[0], "answer": self.faq.render_answer(m[0], placeholders)}

        return facts

    def _compose_draft(self, route: Dict[str, Any], facts: Dict[str, Any], ctx: MessageContext) -> str:
        intent = route.get("intent")
        ent = route.get("entities", {})
        # Delivery
        if intent in {"check_delivery", "ask_postcode"} and facts.get("delivery"):
            d = facts["delivery"]
            if d["rule"]:
                return f"Yes, we deliver to {d['postcode']}. {d['summary']}."
            return f"We currently don’t deliver to {d['postcode']}."
        # Items
        if intent in {"search_product", "browse_category"} and facts.get("items"):
            items = facts["items"]
            names = ", ".join(i.get("name") or i.get("_norm_name", "") for i in items[:3])
            if names:
                return f"Top picks: {names}. Want prices or more options?"
            return "I couldn’t find matching items."
        # Price
        if intent == "price_check" and facts.get("price"):
            p = facts["price"]
            if p["price"] is not None:
                stock = "in stock" if p.get("in_stock") else "out of stock"
                return f"{p['sku']} is £{p['price']:.2f} and {stock}."
            return f"I couldn’t find a price for {p['sku']}."
        # FAQ
        if facts.get("faq"):
            return facts["faq"]["answer"]

        # Generic minimal
        return route.get("clarifier") or "Could you clarify what you need?"

    def _update_crm(self, ctx: MessageContext, user_text: str, reply: str, route: Dict[str, Any], facts: Dict[str, Any]) -> None:
        # Lightweight: ensure a lead exists (channel/session-based)
        lead = self.crm.upsert_lead(
            ctx.tenant,
            name=None,
            phone=self._maybe_phone(route),
            channel=ctx.channel,
            session_id=ctx.session_id,
            tags=[route.get("intent")] if route.get("intent") else None,
        )
        self.crm.append_conversation(
            ctx.tenant,
            lead_id=lead.get("id") or lead.get("_id") or "unknown",
            message={
                "from": "user",
                "text": user_text,
                "route": route,
            },
        )
        self.crm.append_conversation(
            ctx.tenant,
            lead_id=lead.get("id") or lead.get("_id") or "unknown",
            message={
                "from": "assistant",
                "text": reply,
                "facts": facts,
            },
        )

    def _post_analytics(self, ctx: MessageContext, user_text: str, reply: str, route: Dict[str, Any], *, mode: str, ok: bool):
        self.analytics.log_event(
            ctx.tenant,
            {
                "type": "chat_turn",
                "mode": mode,
                "intent": route.get("intent"),
                "ok": ok,
                "channel": ctx.channel,
                "latency_ms": route.get("_latency_ms"),
                "session_id": ctx.session_id,
            },
        )
        if route.get("intent") in {"search_product", "price_check", "browse_category"}:
            self.analytics.kpi_increment(ctx.tenant, "product_queries", 1)

    def _make_reply(self, text: str, ctx: MessageContext, route: Dict[str, Any], *, mode: str, facts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "reply": self.rewriter.rewrite(text, style="sales"),
            "mode": mode,
            "intent": route.get("intent"),
            "entities": route.get("entities"),
            "facts": facts or {},
        }

    def _load_session(self, ctx: MessageContext) -> Dict[str, Any]:
        return {
            "postcode": self.memory.get(ctx.session_id, "postcode"),
            "nearest_branch_id": self.memory.get(ctx.session_id, "nearest_branch_id"),
            "last_category": self.memory.get(ctx.session_id, "last_category"),
            "last_sku": self.memory.get(ctx.session_id, "last_sku"),
        }

    def _save_session(self, ctx: MessageContext, sess: Dict[str, Any], route: Dict[str, Any], facts: Dict[str, Any]) -> None:
        ttl = DEFAULT_SESSION_TTL
        ent = route.get("entities", {})
        if ent.get("postcode"):
            self.memory.set(ctx.session_id, "postcode", ent["postcode"], ttl=ttl)
        if facts.get("branch", {}).get("nearest", {}).get("id"):
            self.memory.set(ctx.session_id, "nearest_branch_id", facts["branch"]["nearest"]["id"], ttl=ttl)
        if ent.get("category"):
            self.memory.set(ctx.session_id, "last_category", ent["category"], ttl=ttl)
        if ent.get("sku"):
            self.memory.set(ctx.session_id, "last_sku", ent["sku"], ttl=ttl)

    def _maybe_phone(self, route: Dict[str, Any]) -> Optional[str]:
        ent = route.get("entities", {})
        phone = ent.get("phone")
        if isinstance(phone, str) and phone.strip():
            return phone.strip()
        return None
