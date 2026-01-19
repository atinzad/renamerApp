from __future__ import annotations


def infer_schema_from_example(example_json: dict) -> dict:
    if not isinstance(example_json, dict):
        return _object_schema({})
    properties: dict[str, dict] = {}
    for key, value in example_json.items():
        properties[str(key)] = _infer_schema(value)
    return _object_schema(properties)


def build_instruction_from_example(schema: dict) -> str:
    _ = schema
    return 'Extract fields according to this schema. If a field is missing, return "UNKNOWN".'


def _infer_schema(value: object) -> dict:
    if isinstance(value, dict):
        properties = {str(key): _infer_schema(val) for key, val in value.items()}
        return _object_schema(properties)
    if isinstance(value, list):
        return _array_schema(value)
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"type": "number"}
    return {"type": "string"}


def _array_schema(values: list) -> dict:
    if not values:
        return {"type": "array", "items": {"type": "string"}}
    if any(isinstance(item, dict) for item in values):
        first_dict = next(item for item in values if isinstance(item, dict))
        items_schema = _infer_schema(first_dict)
        return {"type": "array", "items": items_schema}
    return {"type": "array", "items": {"type": "string"}}


def _object_schema(properties: dict[str, dict]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties.keys()),
        "additionalProperties": False,
    }
