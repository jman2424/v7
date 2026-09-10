"""Validation for editable settings that do not yet have a full JSON schema."""
from urllib.parse import urlsplit

from flask import abort


def validate_settings(filename, payload):
    if filename == "overrides.json":
        ai = payload.get("ai", {})
        if not isinstance(ai, dict):
            abort(400, description="Invalid agent settings")
        mode = ai.get("mode")
        if mode is not None and (not isinstance(mode, str) or mode.upper() not in {"V5", "V6", "V7", "AIV5", "AIV6", "AIV7"}):
            abort(400, description="Invalid agent mode")
    if filename == "branding.json":
        origins = payload.get("allowed_origins", [])
        if not isinstance(origins, list) or len(origins) > 30:
            abort(400, description="Expected a list of approved website origins")
        for origin in origins:
            if not isinstance(origin, str):
                abort(400)
            parsed = urlsplit(origin)
            if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
                abort(400, description="Origins must be exact http(s) origins without paths")
        for section, keys in {"widget": ("avatar",), "": ("favicon",)}.items():
            data = payload.get(section, {}) if section else payload
            if not isinstance(data, dict):
                abort(400)
            for key in keys:
                url = data.get(key, "")
                if not isinstance(url, str) or (url and not url.startswith(("/", "https://"))):
                    abort(400, description="Image URLs must use HTTPS or a local path")
