from __future__ import annotations

from app.domain.label_fallback import LabelFallbackCandidate, LabelFallbackClassification
from app.ports.llm_port import LLMPort


class MockLLMAdapter(LLMPort):
    def classify_label(
        self, ocr_text: str, candidates: list[LabelFallbackCandidate]
    ) -> LabelFallbackClassification:
        return LabelFallbackClassification(
            label_name=None, confidence=0.0, signals=["LLM_NOT_CONFIGURED"]
        )

    def extract_fields(
        self, schema: dict, ocr_text: str, instructions: str | None = None
    ) -> dict:
        _ = instructions
        return {key: "UNKNOWN" for key in _schema_keys(schema)}

    def extract_fields_from_image(
        self,
        schema: dict,
        file_bytes: bytes,
        mime_type: str,
        instructions: str | None = None,
    ) -> dict:
        _ = file_bytes
        _ = mime_type
        _ = instructions
        return {key: "UNKNOWN" for key in _schema_keys(schema)}


def _schema_keys(schema: dict) -> list[str]:
    if not isinstance(schema, dict):
        return []
    properties = schema.get("properties")
    if isinstance(properties, dict):
        return list(properties.keys())
    return list(schema.keys())
