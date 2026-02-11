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
