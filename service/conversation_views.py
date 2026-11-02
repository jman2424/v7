"""Public, tenant-scoped references for the authorised conversation reader."""
import hashlib
import hmac
import json
from collections.abc import Mapping
from sqlite3 import Row
from typing import Any


def conversation_message(row: Mapping[str, Any] | Row, tenant: str, secret: str | bytes) -> dict[str, Any]:
    message = dict(row)
    session = message.pop('session_id', None)
    message['conversation_ref'] = None
    if session:
        key = secret.encode('utf-8') if isinstance(secret, str) else secret
        value = json.dumps([tenant, message.get('channel'), str(session)],
                           ensure_ascii=True, separators=(',', ':')).encode('utf-8')
        message['conversation_ref'] = hmac.new(
            key, b'v7-conversation-view-v1\0'+value, hashlib.sha256).hexdigest()[:32]
    return message
