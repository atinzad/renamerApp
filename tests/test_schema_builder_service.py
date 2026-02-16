import json

from app.services.schema_builder_service import SchemaBuilderService


class _RecordingStorage:
    def __init__(self) -> None:
        self.schema_updates: list[tuple[str, str]] = []
        self.instructions_updates: list[tuple[str, str]] = []

    def update_label_extraction_schema(self, label_id: str, schema_json: str) -> None:
        self.schema_updates.append((label_id, schema_json))

    def update_label_extraction_instructions(self, label_id: str, instructions: str) -> None:
        self.instructions_updates.append((label_id, instructions))


class _RecordingLLM:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, str, str | None]] = []

    def extract_fields(
        self, schema: dict, ocr_text: str, instructions: str | None = None
    ) -> dict:
        self.calls.append((schema, ocr_text, instructions))
        return {
            "schema": {
                "type": "object",
                "properties": {
                    "document_number": {"type": "string"},
                },
                "required": ["document_number"],
                "additionalProperties": False,
            },
            "instructions": "ignored",
        }


def test_build_from_ocr_guidance_override_is_prompt_not_ocr_text() -> None:
    storage = _RecordingStorage()
    llm = _RecordingLLM()
    service = SchemaBuilderService(storage=storage, llm=llm)

    guidance = "Only include issuer_name, document_number, and issue_date."
    ocr_text = "Document Number: 12345\nIssuer: Ministry of Interior"

    schema, _ = service.build_from_ocr(
        "label-1", ocr_text, guidance_override=guidance
    )

    assert llm.calls
    first_call = llm.calls[0]
    assert first_call[1] == ocr_text
    assert first_call[2] is not None
    assert guidance in first_call[2]

    assert storage.schema_updates
    stored_schema = json.loads(storage.schema_updates[-1][1])
    assert stored_schema == schema
    assert "document_number" in stored_schema.get("properties", {})
    assert storage.instructions_updates


def test_build_from_ocr_only_include_guidance_is_enforced() -> None:
    storage = _RecordingStorage()
    llm = _RecordingLLM()
    service = SchemaBuilderService(storage=storage, llm=llm)

    guidance = "Only include issuer_name, document_number, and issue_date."
    ocr_text = "Document Number: 12345\nIssuer: Ministry of Interior"

    schema, _ = service.build_from_ocr(
        "label-1", ocr_text, guidance_override=guidance
    )

    properties = schema.get("properties", {})
    assert set(properties.keys()) == {"issuer_name", "document_number", "issue_date"}
    assert properties["issue_date"] == {"type": "string"}
    assert schema.get("required") == ["issuer_name", "document_number", "issue_date"]


def test_build_from_ocr_include_only_guidance_is_enforced() -> None:
    storage = _RecordingStorage()
    llm = _RecordingLLM()
    service = SchemaBuilderService(storage=storage, llm=llm)

    guidance = "Include only commercial_registry_number and company_status."
    ocr_text = "Status: Active\nRegistry: 998877"

    schema, _ = service.build_from_ocr(
        "label-1", ocr_text, guidance_override=guidance
    )

    properties = schema.get("properties", {})
    assert set(properties.keys()) == {"commercial_registry_number", "company_status"}
    assert schema.get("required") == ["commercial_registry_number", "company_status"]


def test_build_from_ocr_extract_nothing_else_and_patterns_guidance() -> None:
    storage = _RecordingStorage()
    llm = _RecordingLLM()
    service = SchemaBuilderService(storage=storage, llm=llm)

    guidance = (
        "Extract the Civil ID number, the Name, and the Expiry Date. "
        "Nothing else. Detect patterns and add them to the Extraction instructions."
    )
    ocr_text = "Civil ID: 287012345678\nName: John Doe\nExpiry Date: 2028-01-31"

    _, instructions = service.build_from_ocr(
        "label-1", ocr_text, guidance_override=guidance
    )

    stored_schema = json.loads(storage.schema_updates[-1][1])
    properties = stored_schema.get("properties", {})
    assert set(properties.keys()) == {"civil_number", "name", "expiry_date"}
    assert "text patterns" in instructions.lower()
