from __future__ import annotations

import time
import uuid
from flask import Blueprint, request, jsonify, render_template, current_app

from routes import get_container
from connectors.web_widget import parse_inbound, send_reply

bp = Blueprint("webchat", __name__)

ALLOWED_WEB_ORIGIN = "https://web-tester-jnwd.onrender.com"


def _add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_WEB_ORIGIN
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return resp


def _short(x, n=300):
    try:
        s = str(x)
    except Exception:
        return "<unprintable>"
    return s if len(s) <= n else s[:n] + "…"


@bp.get("/chat_ui")
def chat_ui():
    c = get_container()
    session_id = request.args.get("session") or ""
    tenant = request.args.get("tenant") or c.settings.BUSINESS_KEY
    return render_template("chatbot.html", session_id=session_id, tenant=tenant)


@bp.route("/chat_api", methods=["POST", "OPTIONS"])
def chat_api():
    rid = uuid.uuid4().hex[:10]
    t0 = time.time()

    if request.method == "OPTIONS":
        resp = jsonify({})
        return _add_cors_headers(resp)

    c = get_container()

    # ---- parse JSON safely ----
    try:
        data = request.get_json(force=True) or {}
    except Exception as e:
        current_app.logger.exception("[%s] /chat_api invalid JSON: %s", rid, e)
        resp = jsonify({"error": "invalid_json"})
        resp.status_code = 400
        return _add_cors_headers(resp)

    current_app.logger.info(
        "[%s] /chat_api IN origin=%s ip=%s keys=%s body.message=%s",
        rid,
        request.headers.get("Origin"),
        request.remote_addr,
        list(data.keys()),
        _short(data.get("message") or data.get("text")),
    )

    # ---- normalise inbound ----
    events = parse_inbound(
        data,
        default_tenant=c.settings.BUSINESS_KEY,
        default_channel="web",
        remote_addr=request.remote_addr,
    )

    current_app.logger.info(
        "[%s] parsed events count=%s first=%s",
        rid,
        len(events),
        _short(events[0] if events else None),
    )

    if not events:
        resp = jsonify({"error": "missing_message"})
        resp.status_code = 400
        return _add_cors_headers(resp)

    event = events[0]
    text = event.get("text", "")
    session_id = event.get("session_id")
    tenant = event.get("tenant")
    channel = event.get("channel")
    metadata = event.get("metadata")

    # ---- try the real pipeline (router.route OR message_handler.handle) ----
    result = None

    # 1) Try service.router.route(c, event=event)
    try:
        from service import router as router_mod  # type: ignore
        if hasattr(router_mod, "route"):
            current_app.logger.info("[%s] calling service.router.route(...)", rid)
            result = router_mod.route(c, event=event)
            current_app.logger.info(
                "[%s] router.route returned type=%s keys=%s reply=%s",
                rid,
                type(result).__name__,
                list(result.keys()) if isinstance(result, dict) else None,
                _short(result.get("reply")) if isinstance(result, dict) else None,
            )
    except Exception:
        current_app.logger.exception("[%s] router.route crashed", rid)
        result = None

    # 2) Try service.message_handler.handle(c, text=..., ...)
    if result is None:
        try:
            from service import message_handler as mh  # type: ignore
            if hasattr(mh, "handle"):
                current_app.logger.info("[%s] calling service.message_handler.handle(...)", rid)
                result = mh.handle(
                    c,
                    text=text,
                    session_id=session_id,
                    channel=channel,
                    tenant=tenant,
                    metadata=metadata,
                )
                current_app.logger.info(
                    "[%s] message_handler.handle returned type=%s keys=%s reply=%s",
                    rid,
                    type(result).__name__,
                    list(result.keys()) if isinstance(result, dict) else None,
                    _short(result.get("reply")) if isinstance(result, dict) else None,
                )
        except Exception:
            current_app.logger.exception("[%s] message_handler.handle crashed", rid)
            result = None

    # ---- if still no usable result, FALL BACK but LOG WHY ----
    if not isinstance(result, dict) or "reply" not in result:
        current_app.logger.warning(
            "[%s] NO PIPELINE RESULT -> falling back to echo. result_type=%s",
            rid,
            type(result).__name__ if result is not None else None,
        )
        result = {
            "reply": f"I received: {text}",
            "intent": "stub_web_echo",
            "resolved": True,
            "tenant": tenant,
            "channel": channel,
        }

    # ---- build response ----
    resp_payload = send_reply(event, result.get("reply", ""), raw=result)
    dt_ms = int((time.time() - t0) * 1000)

    current_app.logger.info(
        "[%s] /chat_api OUT status=200 ms=%s reply=%s",
        rid,
        dt_ms,
        _short(resp_payload.get("reply")),
    )

    resp = jsonify({"reply": resp_payload["reply"], "raw": resp_payload["raw"]})
    return _add_cors_headers(resp)
