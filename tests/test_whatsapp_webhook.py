"""
WhatsApp webhook tests:
- GET verification handshake
- POST inbound message with signature verification bypassed via monkeypatch
"""

from __future__ import annotations
import json
import hmac
import hashlib
import pytest


def test_webhook_verify_challenge(client, app, monkeypatch):
    # Ensure app has a known verify token
    app.config["WA_VERIFY_TOKEN"] = "testtoken"
    r = client.get("/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=testtoken&hub.challenge=12345")
    # Some frameworks return text/plain, others JSON; status 200 is key
    assert r.status_code == 200
    # Body should contain the challenge or echo JSON
    body = r.get_data(as_text=True)
    assert "12345" in body or r.is_json and (r.get_json() or {}).get("challenge") == "12345"


def test_webhook_inbound_dispatch_ok(client, monkeypatch):
    # Bypass signature verification in connector
    def ok_verify(*args, **kwargs):
        return True

    def parse_inbound(payload):
        # Minimal normalized record the route expects to work with
        return {
            "phone": "+447700900123",
            "name": "Test User",
            "text": "hello there",
            "timestamp": 1700000000
        }

    # Monkeypatch connector helpers
    monkeypatch.setattr("connectors.whatsapp.verify_signature", ok_verify, raising=False)
    monkeypatch.setattr("connectors.whatsapp.parse_inbound", lambda p: parse_inbound(p), raising=False)

    # Build a plausible incoming request
    payload = {"entry": [{"changes": [{"value": {"messages": [{"text": {"body": "hello there"}}]}}]}]}
    body = json.dumps(payload).encode("utf-8")

    # Some implementations check an X-Hub-Signature header; provide a dummy
    sig = hmac.new(b"dummy", body, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": f"sha256={sig}"
    }

    r = client.post("/whatsapp/webhook", data=body, headers=headers)
    assert r.status_code in (200, 202)
    if r.is_json:
        status = (r.get_json() or {}).get("status", "").lower()
        assert status in ("ok", "accepted", "queued", "")
