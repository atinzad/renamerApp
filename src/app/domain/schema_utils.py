from __future__ import annotations

from typing import Iterable


def apply_missing_field_policy(
    schema: dict, extracted: dict
) -> tuple[dict, list[str], bool]:
    keys, required_keys = _schema_keys(schema)
    normalized: dict = dict(extracted) if extracted else {}
    warnings: list[str] = []
    needs_review = False
    for key in keys:
        value = normalized.get(key)
        is_missing = _is_empty(value)
        if is_missing and key in required_keys:
            normalized[key] = "UNKNOWN"
            warnings.append(f"Missing required field: {key}")
            needs_review = True
        elif key not in normalized:
            normalized[key] = ""
    return normalized, warnings, needs_review


def _schema_keys(schema: dict) -> tuple[list[str], set[str]]:
    if not isinstance(schema, dict):
        return [], set()
    properties = schema.get("properties")
    if isinstance(properties, dict):
        keys = list(properties.keys())
        required = schema.get("required")
        if isinstance(required, list):
            required_keys = {str(item) for item in required}
        else:
            required_keys = set(keys)
        return keys, required_keys
    keys = list(schema.keys())
    return keys, set(keys)


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, set, tuple)):
        return len(value) == 0
    return False
