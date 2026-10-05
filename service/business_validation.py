"""Validation for editable settings that do not yet have a full JSON schema."""
import json
from urllib.parse import urlsplit

from flask import abort
from jsonschema import Draft202012Validator

from service.sales_playbook import (
    BUSINESS_MODELS,
    CUSTOMER_TYPES,
    FULFILMENT_MODES,
    MAX_BUSINESS_FOCUS_LENGTH,
    MAX_HANDOFF_MESSAGE_LENGTH,
    MAX_IDEAL_CUSTOMER_LENGTH,
    MAX_QUALIFICATION_QUESTION_LENGTH,
    MAX_QUALIFICATION_QUESTIONS,
    MAX_RESPONSE_GUIDANCE_LENGTH,
    MAX_VALUE_PROPOSITION_LENGTH,
    MAX_VALUE_PROPOSITIONS,
    SalesPlaybookValidationError,
    validate_sales_playbook,
)


def _object(properties):
    return {"type": "object", "properties": properties, "additionalProperties": False}


def _text(maximum=2000):
    return {"type": "string", "maxLength": maximum}


def _strings(maximum, length):
    return {"type": "array", "maxItems": maximum, "items": _text(length)}


_BOOL = {"type": "boolean"}
_COLOR = {"type": "string", "pattern": r"^#[0-9a-fA-F]{6}$"}
_ORIGINS = {"type": "array", "maxItems": 30, "uniqueItems": True, "items": _text(2048)}
_SETTINGS = {
    "branding.json": _object({
        "theme": _object({**{key: _COLOR for key in (
            "primary_color", "secondary_color", "accent_color", "text_color")},
            "font_family": _text(200)}),
        "widget": _object({
            "avatar": _text(500), "greeting": _text(240), "chat_title": _text(80),
            "assistant_name": _text(80), "company_logo_url": _text(500),
            "style": {"type": "string", "enum": ["midnight", "daylight", "minimal", "editorial", "neon", "warm", "glass"]},
            "accent_color": _COLOR, "allowed_origins": _ORIGINS,
        }),
        "logo": _object({"light": _text(2000), "dark": _text(2000)}),
        "favicon": _text(2000), "allowed_origins": _ORIGINS,
    }),
    "store_info.json": _object({
        "name": {"type": "string", "minLength": 1, "maxLength": 120},
        "about": _text(1200), "email": _text(320), "phone": _text(80), "website": _text(500),
        "halal_certified": _BOOL, "certifications": _strings(30, 120),
        "social": {"type": "object", "maxProperties": 30,
                   "propertyNames": {"type": "string", "minLength": 1, "maxLength": 80},
                   "additionalProperties": _text(500)},
    }),
    "overrides.json": _object({
        "ai": _object({"mode": _text(20)}),
        "tone": _object({"style": _text(200), "max_sentences": {"type": "integer", "minimum": 1, "maximum": 100}}),
        "recommendations": _object({"related_count": {"type": "integer", "minimum": 0, "maximum": 100},
                                     "show_out_of_stock": _BOOL}),
        "thresholds": _object({"search_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                               "geo_radius_km": {"type": "number", "minimum": 0, "maximum": 20000}}),
        "filters": _object({"exclude_tags": _strings(100, 200)}),
        "self_repair": _object({"auto_suggest_synonyms": _BOOL, "log_issues_only": _BOOL}),
        "sales_playbook": _object({
            "business_model": {"type": "string", "enum": sorted(BUSINESS_MODELS)},
            "fulfilment_mode": {"type": "string", "enum": sorted(FULFILMENT_MODES)},
            "customer_type": {"type": "string", "enum": sorted(CUSTOMER_TYPES)},
            "response_guidance": _text(MAX_RESPONSE_GUIDANCE_LENGTH),
            "business_focus": _text(MAX_BUSINESS_FOCUS_LENGTH),
            "ideal_customer": _text(MAX_IDEAL_CUSTOMER_LENGTH),
            "value_propositions": _strings(MAX_VALUE_PROPOSITIONS, MAX_VALUE_PROPOSITION_LENGTH),
            "offering_type": _text(40), "primary_goal": _text(40),
            "qualification_questions": _strings(MAX_QUALIFICATION_QUESTIONS, MAX_QUALIFICATION_QUESTION_LENGTH),
            "handoff_message": _text(MAX_HANDOFF_MESSAGE_LENGTH),
        }),
    }),
    "synonyms.json": {"type": "object", "maxProperties": 5000,
        "propertyNames": {"type": "string", "minLength": 1, "maxLength": 200},
        "additionalProperties": {"oneOf": [_text(200), _strings(100, 200)]}},
}


def _http_url(value):
    try:
        if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value) or "\\" in value:
            return False
        parsed = urlsplit(value)
        return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None and parsed.port != 0)
    except ValueError:
        return False


def _validate_origins(origins, *, loopback_http_only=False):
    for origin in origins:
        try:
            parsed = urlsplit(origin)
        except ValueError:
            abort(400, description="Invalid website origin")
        if not _http_url(origin) or parsed.path or parsed.query or parsed.fragment:
            abort(400, description="Origins must be exact http(s) origins without paths")
        if loopback_http_only and parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            abort(400, description="Approved website domains must use HTTPS")


def _image_url(value):
    if not value:
        return True
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value) or "\\" in value:
        return False
    return ((value.startswith("/") and not value.startswith("//"))
            or (value.startswith("https://") and _http_url(value)))


def validate_settings(filename, payload):
    # Catalogues, offers, delivery and other documents have their own schemas.
    # Their callers invoke this function too; only these four settings use it.
    schema = _SETTINGS.get(filename)
    if schema is None:
        return
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        abort(400, description="Settings must contain valid JSON values")
    if not Draft202012Validator(schema).is_valid(payload):
        abort(400, description="Settings contain unsupported fields or invalid values")
    if filename == "overrides.json":
        ai = payload.get("ai", {})
        if not isinstance(ai, dict):
            abort(400, description="Invalid agent settings")
        mode = ai.get("mode")
        if mode is not None and (not isinstance(mode, str) or mode.upper() not in {"V5", "V6", "V7", "AIV5", "AIV6", "AIV7"}):
            abort(400, description="Invalid agent mode")
        if "sales_playbook" in payload:
            try:
                validate_sales_playbook(payload["sales_playbook"])
            except SalesPlaybookValidationError:
                abort(400, description="Invalid sales playbook")
    if filename == "branding.json":
        _validate_origins(payload.get("allowed_origins", []))
        _validate_origins(payload.get("widget", {}).get("allowed_origins", []), loopback_http_only=True)
        for section, keys in {"widget": ("avatar", "company_logo_url"), "logo": ("light", "dark"), "": ("favicon",)}.items():
            data = payload.get(section, {}) if section else payload
            if not isinstance(data, dict):
                abort(400)
            for key in keys:
                url = data.get(key, "")
                if not _image_url(url):
                    abort(400, description="Image URLs must use HTTPS or a local path")
    if filename == "store_info.json":
        for url in [payload.get("website", ""), *payload.get("social", {}).values()]:
            if url and not _http_url(url):
                abort(400, description="Website links must use HTTP or HTTPS")
