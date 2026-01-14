from __future__ import annotations

import json
import re


_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def validate_schema_config(schema_json: str, naming_template: str) -> list[str] | None:
    errors: list[str] = []
    try:
        parsed = json.loads(schema_json) if schema_json.strip() else {}
    except json.JSONDecodeError as exc:
        errors.append(f"Schema JSON invalid: {exc}")
        return errors

    if not isinstance(parsed, dict):
        errors.append("Schema JSON must be an object.")
        return errors

    for key, value in parsed.items():
        if isinstance(value, (dict, list)):
            errors.append(f"Schema field '{key}' must be a primitive value, not nested.")

    placeholders = _PLACEHOLDER_RE.findall(naming_template or "")
    if not parsed and placeholders:
        errors.append("Naming template has placeholders but schema is empty.")
    else:
        for placeholder in placeholders:
            if placeholder not in parsed:
                errors.append(f"Naming template placeholder '{placeholder}' missing in schema.")

    return None if not errors else errors
