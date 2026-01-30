# routes/webchat_routes.py
from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify, render_template, make_response

from routes import get_container
from connectors.web_widget import parse_inbound, send_reply

logger = logging.getLogger("WEB.Chat")
bp = Blueprint("webchat", __name__)

ALLOWED_ORIGIN = "https://web-tester-jnwd.onrender.com"


def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    return resp


def _get_handler(container):
    h = getattr(container, "handler", None) or getattr(container, "message_handler", None)
    if h is not None:
        return h

    logger.warning("WEB: No MessageHandler on container. Creating one.")
    try:
        from service.message_handler import MessageHandler
        h = MessageHandler(container)
        container.handler = h
        return h
    except Exception:
        logger.exception("WEB: Failed to create MessageHandler")
        return None


def _safe_log_message(
    c,
    *,
    tenant: str,
    channel: str,
    direction: str,
    session_id: str,
    text: str,
    intent: str = "unknown",
    lead_id: str | None = None,
    store: str | None = None,
    products: list[str] | None = None,
    is_fallback: bool = False,
    is_error: bool = False,
    extra: dict | None = None,
) -> None:
    """
    Analytics should never crash chat flow.
    """
    try:
        if getattr(c, "analytics", None) is None:
            return
        c.analytics.log_message(
            tenant=tenant,
            channel=channel,
            direction=direction,
            session_id=session_id,
            text=text or "",
            intent=intent or "unknown",
            lead_id=lead_id,
            store=store,
            products=products or [],
            is_fallback=bool(is_fallback),
            is_error=bool(is_error),
            extra=extra or {},
        )
    except Exception:
        return


def _extract_store_from_result(result: dict) -> str | None:
    """
    Best-effort: different handlers return different shapes.
    We normalize into a single string for analytics pie.
    """
    if not isinstance(result, dict):
        return None

    # Common: result["store"] = "Southall"
    store = result.get("store")
    if isinstance(store, str) and store.strip():
        return store.strip()

    # Common: entities.branch / entities.store / entities.location
    entities = result.get("entities") or {}
    if isinstance(entities, dict):
        for k in ("store", "branch", "location", "nearest_store", "nearest_branch"):
            v = entities.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, dict):
                # e.g. {"name": "..."}
                name = v.get("name") or v.get("title")
                if isinstance(name, str) and name.strip():
                    return name.strip()

    # Some routers: result["meta"]["store"]
    meta = result.get("meta") or {}
    if isinstance(meta, dict):
        v = meta.get("store") or meta.get("branch") or meta.get("location")
        if isinstance(v, str) and v.strip():
            return v.strip()

    return None


def _extract_products_from_result(result: dict) -> list[str]:
    """
    Best-effort products list for future charts.
    """
    if not isinstance(result, dict):
        return []

    prods = result.get("products")
    if isinstance(prods, list):
        out = []
        for p in prods:
            if isinstance(p, str) and p.strip():
                out.append(p.strip())
            elif isinstance(p, dict):
                name = p.get("name") or p.get("title")
                if isinstance(name, str) and name.strip():
                    out.append(name.strip())
        return out

    entities = result.get("entities") or {}
    if isinstance(entities, dict):
        # some handlers put matches here
        matches = entities.get("products") or entities.get("product_matches")
        if isinstance(matches, list):
            out = []
            for p in matches:
                if isinstance(p, str) and p.strip():
                    out.append(p.strip())
                elif isinstance(p, dict):
                    name = p.get("name") or p.get("title")
                    if isinstance(name, str) and name.strip():
                        out.append(name.strip())
            return out

    return []


def _is_fallback_result(result: dict, intent: str) -> bool:
    """
    We mark fallback using multiple signals so you actually see counts.
    """
    if not isinstance(result, dict):
        return False

    # explicit flags
    for k in ("is_fallback", "fallback", "did_fallback"):
        v = result.get(k)
        if v is True:
            return True

    # if handler sets mode/type
    if str(result.get("route") or "").lower() in ("fallback", "default"):
        return True

    # intent-based heuristics
    bad_intents = {
        "unknown",
        "fallback",
        "default",
        "clarify",
        "needs_clarification",
        "no_match",
    }
    if (intent or "").strip().lower() in bad_intents:
        return True

    # some handlers return confidence
    conf = result.get("confidence")
    try:
        if conf is not None and float(conf) < 0.35:
            return True
    except Exception:
        pass

    return False


@bp.get("/chat_ui")
def chat_ui():
    c = get_container()
    session_id = request.args.get("session") or ""
    tenant = request.args.get("tenant") or c.settings.BUSINESS_KEY
    return render_template("chatbot.html", session_id=session_id, tenant=tenant)


@bp.route("/chat_api", methods=["OPTIONS"])
def chat_api_options():
    return _cors(make_response("", 200))


@bp.route("/chat_api", methods=["POST"])
def chat_api():
    c = get_container()

    try:
        data = request.get_json(force=True) or {}
    except Exception:
        logger.exception("WEB: Invalid JSON payload")
        return _cors(jsonify({"error": "invalid_json"})), 400

    events = parse_inbound(
        data,
        default_tenant=c.settings.BUSINESS_KEY,
        default_channel="web",
        remote_addr=request.remote_addr,
    )
    if not events:
        return _cors(jsonify({"error": "missing_message"})), 400

    ev = events[0]
    text = (ev.get("text") or "").strip()
    session_id = (ev.get("session_id") or "").strip() or "web_unknown"
    tenant = (ev.get("tenant") or "").strip() or c.settings.BUSINESS_KEY
    channel = (ev.get("channel") or "web").strip().lower() or "web"
    metadata = ev.get("metadata") or {}

    logger.info("WEB IN: tenant=%s session=%s channel=%s text=%r", tenant, session_id, channel, text)

    # ✅ LOG inbound message
    _safe_log_message(
        c,
        tenant=tenant,
        channel="web",
        direction="inbound",
        session_id=session_id,
        text=text,
        intent="unknown",
        extra={
            "ip": request.remote_addr,
            "ua": request.headers.get("User-Agent", ""),
            "tenant": tenant,
        },
    )

    handler = _get_handler(c)
    is_error = False

    if handler is None:
        is_error = True
        result = {"reply": "Sorry—bot not configured.", "intent": "system_error", "entities": {}}
    else:
        try:
            result = handler.handle(
                text,
                tenant=tenant,
                session_id=session_id,
                channel=channel,
                metadata=metadata,
            ) or {}
        except Exception as exc:
            is_error = True
            logger.exception("WEB: handler.handle crashed: %s", exc)
            result = {"reply": "Sorry—server error.", "intent": "system_error", "entities": {}}

    reply = (result.get("reply") or "").strip()
    intent = (result.get("intent") or "unknown").strip()

    # ✅ derive store/products/fallback
    store = _extract_store_from_result(result)
    products = _extract_products_from_result(result)
    is_fallback = _is_fallback_result(result, intent)

    logger.info("WEB OUT: tenant=%s session=%s intent=%s fallback=%s reply=%r", tenant, session_id, intent, is_fallback, reply)

    # ✅ LOG outbound message (and fallback/error flags)
    _safe_log_message(
        c,
        tenant=tenant,
        channel="web",
        direction="outbound",
        session_id=session_id,
        text=reply,
        intent=intent,
        store=store,
        products=products,
        is_fallback=is_fallback,
        is_error=is_error,
        extra={
            "raw_intent": intent,
            "store": store,
            "products_n": len(products),
        },
    )

    resp_payload = send_reply(ev, reply, raw=result)
    return _cors(jsonify({"reply": resp_payload["reply"], "raw": resp_payload["raw"]})), 200
