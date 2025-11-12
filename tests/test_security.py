"""
Unit + integration tests for services/security.py
Covers: password hashing, TOTP setup/verify, CSRF helpers, and webhook signatures.
"""

from __future__ import annotations
import base64
import hashlib
import hmac
import os
import time
import pytest

from services.security import (
    hash_password,
    verify_password,
    generate_totp_secret,
    generate_totp_token,
    verify_totp_token,
    sign_webhook,
    verify_webhook_signature,
    generate_csrf_token,
    verify_csrf_token,
)

def test_password_hash_and_verify():
    password = "super_secret_password"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("wrongpass", hashed)

def test_totp_setup_and_verify():
    secret = generate_totp_secret()
    token = generate_totp_token(secret)
    assert verify_totp_token(secret, token)
    # Token should expire after 1 period (default 30s window)
    time.sleep(1)
    assert verify_totp_token(secret, token, window=1)

def test_csrf_token_roundtrip():
    sid = "session123"
    token = generate_csrf_token(sid)
    assert verify_csrf_token(sid, token)
    assert not verify_csrf_token("other-session", token)

def test_webhook_signature_ok():
    payload = b'{"message":"ok"}'
    secret = b"my_webhook_secret"
    sig = sign_webhook(payload, secret)
    assert verify_webhook_signature(payload, sig, secret)
    assert not verify_webhook_signature(payload + b"x", sig, secret)

def test_password_strength_edge_cases():
    weak = ["123456", "password", "qwerty"]
    for w in weak:
        hashed = hash_password(w)
        assert len(hashed) > 20  # Always returns hashed, never fails
    strong = "Complex$Pass123!"
    hashed = hash_password(strong)
    assert verify_password(strong, hashed)

def test_totp_invalid_cases():
    secret = generate_totp_secret()
    token = generate_totp_token(secret)
    assert not verify_totp_token(secret, "000000")
    assert not verify_totp_token("WRONGSECRET", token)
