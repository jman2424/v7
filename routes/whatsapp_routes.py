@bp.post("/webhook")
def webhook_receive():
    """
    Receive inbound messages.

    Supports:
      - Meta WhatsApp Cloud API (JSON + X-Hub-Signature-256)
      - Twilio (form-encoded, no X-Hub-Signature-256 → signature check skipped)
    """
    c = get_container()

    # ---- Signature verification (only if Meta header present) ----
    app_secret = getattr(c.settings, "WHATSAPP_APP_SECRET", "")
    sig_header = request.headers.get("X-Hub-Signature-256")

    if app_secret and sig_header:
        # Only enforce verification when Meta is actually calling us
        if not verify_webhook_signature(request, app_secret):
            logger.warning("WA WEBHOOK: invalid X-Hub-Signature, aborting 403.")
            abort(403)
    else:
        # Twilio / other sources: no X-Hub-Signature-256 → skip this check
        logger.debug("WA WEBHOOK: no X-Hub-Signature-256, skipping Meta signature check.")

    # ---- Parse payload safely ----
    # Try JSON first (Meta), then fall back to raw form for Twilio if needed
    payload = {}
    try:
        if request.is_json:
            payload = request.get_json(force=True, silent=True) or {}
        else:
            # Twilio-style form payload -> wrap into a pseudo-Cloud structure if you want
            payload = {"twilio_form": request.form.to_dict()}
        logger.debug("WA WEBHOOK payload: %s", str(payload)[:2000])
    except Exception as exc:
        logger.exception("WA WEBHOOK: invalid payload: %s", exc)
        return jsonify({"error": "invalid payload"}), 400

    # ---- Parse inbound events ----
    try:
        events = parse_inbound(payload)
    except Exception as exc:
        logger.exception("WA WEBHOOK: parse_inbound failed: %s", exc)
        return jsonify({"ok": True, "events": 0}), 200

    if not events:
        logger.debug("WA WEBHOOK: no text events in payload.")
        return jsonify({"ok": True, "events": 0}), 200

    # ---- Process each inbound message ----
    for ev in events:
        try:
            text = (ev.get("text") or "").strip()
            if not text:
                continue

            from_id = ev.get("from") or "unknown"
            session_id = ev.get("session_id") or from_id
            tenant = ev.get("tenant") or c.settings.BUSINESS_KEY

            logger.info(
                "WA IN: tenant=%s session=%s from=%s text=%r",
                tenant,
                session_id,
                from_id,
                text,
            )

            result = message_handler.handle(
                c,
                text=text,
                session_id=session_id,
                channel="wa",
                tenant=tenant,
                metadata={"wa_id": from_id},
            )

            reply = (result.get("reply") or "").strip()
            if reply:
                try:
                    send_reply(ev, reply, settings=c.settings)
                except Exception as send_exc:
                    logger.exception(
                        "WA WEBHOOK: send_reply failed: %s",
                        send_exc,
                        extra={"wa_id": from_id},
                    )

            try:
                c.analytics.log_turn(
                    tenant=tenant,
                    session_id=session_id,
                    intent=result.get("intent"),
                    resolved=bool(result.get("resolved", False)),
                    latency_ms=float(result.get("_latency_ms", 0) or 0),
                )
            except Exception as log_exc:
                logger.exception("Analytics log_turn failed: %s", log_exc)

        except Exception as ev_exc:
            logger.exception("Error processing WA event: %s", ev_exc)

    return jsonify({"ok": True, "events": len(events)}), 200
