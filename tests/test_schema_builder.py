from app.domain.schema_builder import build_instruction_from_example, infer_schema_from_example


def test_infer_schema_from_example_nested() -> None:
    example = {
        "civil_id": "123",
        "address": {"area": "X", "block": "1"},
        "tags": ["a", "b"],
        "items": [{"code": "A"}],
    }
    schema = infer_schema_from_example(example)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"civil_id", "address", "tags", "items"}
    address_schema = schema["properties"]["address"]
    assert address_schema["type"] == "object"
    assert set(address_schema["required"]) == {"area", "block"}
    items_schema = schema["properties"]["items"]
    assert items_schema["type"] == "array"
    assert items_schema["items"]["type"] == "object"
    assert set(items_schema["items"]["required"]) == {"code"}


def test_build_instruction_from_example_non_empty() -> None:
    instruction = build_instruction_from_example({"type": "object", "properties": {}})
    assert instruction
