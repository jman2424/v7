"""Use unambiguous, finite JSON at every HTTP input boundary."""
from __future__ import annotations

import math
from typing import Any

from flask.json.provider import DefaultJSONProvider


def _unique_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate_json_key')
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError('nonfinite_json_number')


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('nonfinite_json_number')
    return number


class StrictJSONProvider(DefaultJSONProvider):
    def loads(self, value: str | bytes, **kwargs: Any) -> Any:
        kwargs.update(object_pairs_hook=_unique_pairs,
                      parse_constant=_invalid_constant, parse_float=_finite_float)
        try:
            data = super().loads(value, **kwargs)
        except RecursionError:
            raise ValueError('json_too_deep') from None
        # Bound nesting before recursive schema validators or business helpers
        # see the input. Legitimate V7 documents use far fewer than 64 levels.
        pending = [(data, 0)]
        while pending:
            item, depth = pending.pop()
            if isinstance(item, (dict, list)):
                if depth >= 64:
                    raise ValueError('json_too_deep')
                children = item.values() if isinstance(item, dict) else item
                pending.extend((child, depth + 1) for child in children)
        return data
