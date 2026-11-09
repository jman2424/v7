"""Turn service failures into reviewed public messages at the HTTP boundary."""
from collections.abc import Iterable

from flask import current_app, jsonify, request


def validation_error(error: BaseException, fallback: str, status: int = 400,
                     public_messages: Iterable[str] = ()):
    for message in public_messages:
        if error.args == (message,):
            return jsonify(error=message), status
    current_app.logger.warning('Validation rejected endpoint=%s error_type=%s',
                               request.endpoint, type(error).__name__)
    return jsonify(error=fallback), status
