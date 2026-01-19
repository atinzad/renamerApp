from __future__ import annotations

import json

from app.domain.schema_builder import (
    build_instruction_from_example,
    infer_schema_from_example,
)
from app.ports.llm_port import LLMPort
from app.ports.storage_port import StoragePort


class SchemaBuilderService:
    def __init__(self, storage: StoragePort, llm: LLMPort) -> None:
        self._storage = storage
        self._llm = llm

    def build_from_example(
        self,
        label_id: str,
        example_json: dict,
        instructions_override: str | None = None,
    ) -> None:
        schema = infer_schema_from_example(example_json)
        instructions = instructions_override
        if not instructions:
            instructions = build_instruction_from_example(schema)
        self._storage.update_label_extraction_schema(
            label_id, json.dumps(schema)
        )
        self._storage.update_label_extraction_instructions(
            label_id, instructions
        )

    def build_from_ocr(self, label_id: str, ocr_text: str) -> tuple[dict, str]:
        if not ocr_text.strip():
            raise ValueError("OCR text is required.")
        schema_request = {
            "type": "object",
            "properties": {
                "schema": {"type": "object"},
                "instructions": {"type": "string"},
            },
            "required": ["schema", "instructions"],
            "additionalProperties": False,
        }
        guidance = (
            "Generate a JSON schema and concise extraction instructions based on the OCR text. "
            "The schema must be a JSON schema object with type, properties, required, "
            "and additionalProperties=false. Instructions should mention UNKNOWN for missing fields."
        )
        result = self._llm.extract_fields(schema_request, ocr_text, guidance) or {}
        schema = result.get("schema")
        instructions = result.get("instructions", "")
        if not isinstance(schema, dict):
            raise ValueError("LLM did not return a valid schema object.")
        if not isinstance(instructions, str):
            instructions = str(instructions)
        self._storage.update_label_extraction_schema(label_id, json.dumps(schema))
        self._storage.update_label_extraction_instructions(label_id, instructions)
        return schema, instructions
