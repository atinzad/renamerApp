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


class _NoisyLLM:
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
                    "j_vey": {"type": "string"},
                    "i": {"type": "string"},
                    "subnet_fol_ee_braer_32": {"type": "string"},
                    "name": {"type": "string"},
                    "address": {"type": "string"},
                },
                "required": [
                    "j_vey",
                    "i",
                    "subnet_fol_ee_braer_32",
                    "name",
                    "address",
                ],
                "additionalProperties": False,
            },
            "instructions": "ignored",
        }


def test_build_from_ocr_guidance_override_ignores_ocr_text() -> None:
    storage = _RecordingStorage()
    llm = _RecordingLLM()
    service = SchemaBuilderService(storage=storage, llm=llm)

    guidance = "Only include issuer_name, document_number, and issue_date."
    schema, _ = service.build_from_ocr("label-1", "", guidance_override=guidance)
    assert llm.calls == []

    assert storage.schema_updates
    stored_schema = json.loads(storage.schema_updates[-1][1])
    assert stored_schema == schema
    assert set(stored_schema.get("properties", {}).keys()) == {
        "issuer_name",
        "document_number",
        "issue_date",
    }
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


def test_build_from_ocr_do_not_extract_anything_else_guidance_is_enforced() -> None:
    storage = _RecordingStorage()
    llm = _RecordingLLM()
    service = SchemaBuilderService(storage=storage, llm=llm)

    guidance = "Extract The name and the address. Do not extract anything else."
    schema, _ = service.build_from_ocr("label-1", "noisy text", guidance_override=guidance)

    properties = schema.get("properties", {})
    assert set(properties.keys()) == {"name", "address"}


def test_build_from_ocr_guidance_boolean_flag_uses_boolean_type() -> None:
    storage = _RecordingStorage()
    llm = _RecordingLLM()
    service = SchemaBuilderService(storage=storage, llm=llm)

    guidance = (
        "Extract the name and whether signature is filled. "
        "Use a true or false flag for signature. Nothing else."
    )
    schema, _ = service.build_from_ocr("label-1", "", guidance_override=guidance)

    properties = schema.get("properties", {})
    assert properties["name"] == {"type": "string"}
    assert properties["signature_present"] == {"type": "boolean"}


def test_build_from_ocr_filters_noisy_keys_and_keeps_relevant_fields() -> None:
    storage = _RecordingStorage()
    llm = _NoisyLLM()
    service = SchemaBuilderService(storage=storage, llm=llm)

    schema, _ = service.build_from_ocr(
        "label-1",
        "PREPROCESSED_OCR\nName: Jane Doe\nAddress: Kuwait City\nj_vey: noisy",
        guidance_override="",
    )

    properties = schema.get("properties", {})
    assert "name" in properties
    assert "address" in properties
    assert "j_vey" not in properties
    assert "i" not in properties
    assert "subnet_fol_ee_braer_32" not in properties
