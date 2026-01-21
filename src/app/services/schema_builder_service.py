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
        schema, instructions = self._attempt_llm_schema(
            schema_request, ocr_text, guidance
        )
        if schema is None:
            schema, instructions = self._fallback_schema(ocr_text)
        self._storage.update_label_extraction_schema(label_id, json.dumps(schema))
        self._storage.update_label_extraction_instructions(label_id, instructions)
        return schema, instructions

    def _attempt_llm_schema(
        self, schema_request: dict, ocr_text: str, guidance: str
    ) -> tuple[dict | None, str]:
        result = self._llm.extract_fields(schema_request, ocr_text, guidance) or {}
        schema = result.get("schema")
        instructions = result.get("instructions", "")
        if isinstance(schema, dict):
            return schema, self._coerce_instructions(instructions)
        repair_guidance = (
            "Return ONLY a JSON object with keys schema and instructions. "
            "schema must be a JSON schema object. instructions must be a string."
        )
        result = self._llm.extract_fields(
            schema_request, ocr_text, f"{guidance} {repair_guidance}"
        ) or {}
        schema = result.get("schema")
        instructions = result.get("instructions", "")
        if isinstance(schema, dict):
            return schema, self._coerce_instructions(instructions)
        return None, ""

    def _fallback_schema(self, ocr_text: str) -> tuple[dict, str]:
        example = self._ocr_text_to_example(ocr_text)
        schema = infer_schema_from_example(example)
        instructions = build_instruction_from_example(schema)
        return schema, instructions

    @staticmethod
    def _ocr_text_to_example(ocr_text: str) -> dict:
        example: dict[str, object] = {}
        for raw_line in ocr_text.splitlines():
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if key in example:
                existing = example[key]
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    example[key] = [existing, value]
            else:
                example[key] = value
        return example

    @staticmethod
    def _coerce_instructions(instructions: object) -> str:
        if isinstance(instructions, str):
            return instructions
        if instructions is None:
            return ""
        return str(instructions)
