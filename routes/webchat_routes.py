from __future__ import annotations

from flask import Blueprint, request, jsonify, render_template, current_app
from routes import get_container
from connectors.web_widget import parse_inbound, send_reply

bp = Blueprint("webchat", __name__)

# The frontend that is allowed to call /chat_api
ALLOWED_WEB_ORIGIN = "https://web-tester-jnwd.onrender.com"


def _add_cors_headers(resp):
    """
    Add CORS headers so the web-tester frontend can call /chat_api.
    """
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_WEB_ORIGIN
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return resp


@bp.get("/chat_ui")
def chat_ui():
    """
    Renders the chatbot iframe UI.

    Query params:
      - session: optional session id for the web widget
      - tenant: optional tenant key (falls back to BUSINESS_KEY)
    """
    c = get_container()
    session_id = request.args.get("session") or ""
    tenant = request.args.get("tenant") or c.settings.BUSINESS_KEY
    return render_template("chatbot.html", session_id=session_id, tenant=tenant)


# ---- internal helper -------------------------------------------------


def _call_router_dynamic(c, event, *, text, session_id, channel, tenant, metadata):
    """
    Try a bunch of likely router/message-handler entry points.

    This is defensive on purpose: different versions may expose:
      - c.router.handle(...)
      - c.router.route(...)
      - c.router.handle_turn(...)
      - c.router.handle_message(...)
      - service.router.handle(...)
      - service.message_handler.handle_turn(...)

    If any returns a dict with a "reply" key, we treat it as success.
    Otherwise we return None and the caller can fall back.
    """
    # 1) Instance router on the container
    router_obj = getattr(c, "router", None)

    # 2) Also try module-level handlers if available
    try:
        from service import router as router_mod  # type: ignore
    except Exception:
        router_mod = None

    try:
        from service import message_handler as mh_mod  # type: ignore
    except Exception:
        mh_mod = None

    candidates = []

    if router_obj is not None:
        candidates.append(("c.router", router_obj))

    if router_mod is not None:
        candidates.append(("service.router", router_mod))

    if mh_mod is not None:
        candidates.append(("service.message_handler", mh_mod))

    # Nothing to try
    if not candidates:
        current_app.logger.warning("webchat: no router/message_handler available on container")
        return None

    # Argument combinations we will attempt, in order
    base_kwargs = dict(
        text=text,
        session_id=session_id,
        channel=channel,
        tenant=tenant,
        metadata=metadata,
        event=event,
        container=c,
    )

    # For each candidate object, we’ll try these method names:
    method_names = [
        "handle",
        "route",
        "handle_turn",
        "handle_message",
    ]

    # Different call patterns (positional vs keyword)
    def _attempt_call(obj_name, obj, method_name):
        if not hasattr(obj, method_name):
            return None

        fn = getattr(obj, method_name)
        if not callable(fn):
            return None

        # Try several signatures, swallowing TypeError (wrong args)
        # but logging once for debugging.
        # 1) Keywords only (most likely)
        try:
            return fn(
                text=text,
                session_id=session_id,
                channel=channel,
                tenant=tenant,
                metadata=metadata,
            )
        except TypeError:
            pass

        # 2) With container kw
        try:
            return fn(
                container=c,
                text=text,
                session_id=session_id,
                channel=channel,
                tenant=tenant,
                metadata=metadata,
            )
        except TypeError:
            pass

        # 3) With event kw
        try:
            return fn(
                event=event,
                container=c,
            )
        except TypeError:
            pass

        # 4) (container, **kwargs)
        try:
            return fn(
                c,
                text=text,
                session_id=session_id,
                channel=channel,
                tenant=tenant,
                metadata=metadata,
            )
        except TypeError:
            pass

        # 5) (container, event)
        try:
            return fn(c, event)
        except TypeError:
            pass

        # If we got here, signature didn't match any pattern.
        current_app.logger.debug(
            "webchat: method %s.%s did not accept tested signatures",
            obj_name,
            method_name,
        )
        return None

    for obj_name, obj in candidates:
        for method_name in method_names:
            try:
                result = _attempt_call(obj_name, obj, method_name)
            except Exception:
                # Any non-TypeError is a real error: log and continue with others.
                current_app.logger.exception(
                    "webchat: error calling %s.%s – continuing with fallbacks",
                    obj_name,
                    method_name,
                )
                continue

            if isinstance(result, dict) and "reply" in result:
                current_app.logger.debug(
                    "webchat: using result from %s.%s", obj_name, method_name
                )
                return result

    # If nothing worked, return None so caller can fall back.
    return None


# ---- main route ------------------------------------------------------


@bp.route("/chat_api", methods=["POST", "OPTIONS"])
def chat_api():
    """
    Contract (HTTP request JSON):
    {
      "message": str,
      "session_id": str?,             # optional, we fall back to asa_<remote_addr>
      "channel": "web"|"wa"|"api"?,   # optional, defaults to "web"
      "tenant": str?,                 # optional, defaults to BUSINESS_KEY
      "metadata": {}?                 # optional dict
    }

    Returns (HTTP response JSON):
    {
      "reply": str,
      "raw": {...}
    }
    """

    # --- CORS preflight ---
    if request.method == "OPTIONS":
        resp = jsonify({})
        return _add_cors_headers(resp)

    c = get_container()
    data = request.get_json(force=True) or {}

    # Normalise inbound payload into an event
    events = parse_inbound(
        data,
        default_tenant=c.settings.BUSINESS_KEY,
        default_channel="web",
        remote_addr=request.remote_addr,
    )

    if not events:
        resp = jsonify({"error": "missing_message"})
        resp.status_code = 400
        return _add_cors_headers(resp)

    event = events[0]
    text = event["text"]
    session_id = event["session_id"]
    channel = event["channel"]
    tenant = event["tenant"]
    metadata = event["metadata"]

    # ------------------------------------------------------------------
    # MAIN BOT CALL – dynamic router lookup.
    # If nothing usable comes back, we fall back to echo.
    # ------------------------------------------------------------------
    result = _call_router_dynamic(
        c,
        event,
        text=text,
        session_id=session_id,
        channel=channel,
        tenant=tenant,
        metadata=metadata,
    )

    if not isinstance(result, dict) or "reply" not in result:
        # Fallback so the widget never 500s
        reply_text = f"I received: {text}"
        result = {
            "reply": reply_text,
            "intent": "stub_web_echo",
            "resolved": True,
            "_latency_ms": 0,
            "channel": channel,
            "tenant": tenant,
            "metadata": metadata,
        }
    else:
        reply_text = result.get("reply", "")

    # Build response using connector helper
    resp_payload = send_reply(
        event,
        reply_text,
        raw=result,
    )

    resp = jsonify(
        {
            "reply": resp_payload["reply"],
            "raw": resp_payload["raw"],
        }
    )
    return _add_cors_headers(resp)
