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

    def build_from_ocr(
        self,
        label_id: str,
        ocr_text: str,
        guidance_override: str | None = None,
    ) -> tuple[dict, str]:
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
            "Use concise English snake_case keys only. Limit the schema to at most 15 fields, "
            "prioritizing core compliance/KYC fields. The schema must be a JSON schema object with "
            "type, properties, required, and additionalProperties=false. Instructions should mention "
            "UNKNOWN for missing fields. Only use array types when multiple values are expected "
            "(e.g., lists of people or activities). Otherwise use string. Prefer singular keys for "
            "scalar fields; use plural keys only for arrays. Do not use arrays for scalar fields "
            "like numbers, dates, addresses, counts, or statuses. Note: OCR text may list "
            "values on a line followed by a label on the next line prefixed by ':'. Infer field names "
            "from the Arabic label lines when present."
        )
        user_guidance = (guidance_override or "").strip()
        guidance_prefix = ""
        if user_guidance:
            guidance_prefix = (
                "Additional user guidance (treat as constraints unless contradicted by OCR): "
                f"{user_guidance}\n\n"
            )
        refine_guidance = (
            "Review the proposed schema and refine it using the OCR text. "
            "Array fields must use plural names. If a field name is singular, its type must be string. "
            "Ensure no more than 15 fields, keep only core compliance/KYC fields, "
            "and add any missing core fields that are clearly present in the OCR. "
            "Output concise English snake_case keys."
        )
        example = self._ocr_text_to_example(ocr_text)
        detected_fields = sorted(example.keys())
        detected_hint = ""
        if detected_fields:
            detected_hint = (
                "Detected candidate fields from OCR labels: "
                + ", ".join(detected_fields[:40])
                + ". "
            )
        schema, instructions = self._attempt_llm_schema(
            schema_request,
            ocr_text,
            f"{guidance_prefix}{guidance} {detected_hint}",
        )
        if schema is None:
            schema, instructions = self._fallback_schema(ocr_text)
        schema = _sanitize_schema(schema, max_fields=15)
        refinement_payload = (
            "OCR text:\n"
            f"{ocr_text}\n\n"
            "Proposed schema JSON:\n"
            f"{json.dumps(schema)}"
        )
        schema, _ = self._attempt_llm_schema(
            schema_request,
            refinement_payload,
            f"{guidance_prefix}{refine_guidance} {detected_hint}",
        )
        schema = _sanitize_schema(schema or {}, max_fields=15)
        if _count_array_fields(schema) > 3:
            retry_guidance = (
                f"{guidance} Avoid arrays unless the OCR clearly lists multiple entries."
            )
            schema, instructions = self._attempt_llm_schema(
                schema_request,
                ocr_text,
                f"{guidance_prefix}{retry_guidance} {detected_hint}",
            )
            if schema is None:
                schema, instructions = self._fallback_schema(ocr_text)
            schema = _sanitize_schema(schema or {}, max_fields=15)
        if not schema.get("properties"):
            retry_guidance = (
                f"{guidance} Return only the 10-15 most important fields. "
                "Avoid noisy OCR artifacts and make reasonable assumptions about core fields."
            )
            schema, instructions = self._attempt_llm_schema(
                schema_request,
                ocr_text,
                f"{guidance_prefix}{retry_guidance} {detected_hint}",
            )
            if schema is None:
                schema, instructions = self._fallback_schema(ocr_text)
            schema = _sanitize_schema(schema or {}, max_fields=15)
        instructions = build_instruction_from_example(schema)
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
        lines = [line.strip() for line in ocr_text.splitlines()]
        last_value_line = ""
        for raw_line in lines:
            if not raw_line:
                continue
            if ":" in raw_line and not raw_line.lstrip().startswith(":"):
                key, value = raw_line.split(":", 1)
                key = key.strip()
                value = value.strip()
                normalized = _normalize_label_key(key)
                if normalized:
                    _append_example_value(example, normalized, value)
                last_value_line = value or last_value_line
                continue
            if raw_line.lstrip().startswith(":"):
                label = raw_line.lstrip()[1:].strip()
                normalized = _normalize_label_key(label)
                if normalized and last_value_line:
                    _append_example_value(example, normalized, last_value_line)
                continue
            last_value_line = raw_line
        return example

    @staticmethod
    def _coerce_instructions(instructions: object) -> str:
        if isinstance(instructions, str):
            return instructions
        if instructions is None:
            return ""
        return str(instructions)


def _append_example_value(example: dict[str, object], key: str, value: str) -> None:
    if not key:
        return
    if key in example:
        existing = example[key]
        if isinstance(existing, list):
            existing.append(value)
        else:
            example[key] = [existing, value]
    else:
        example[key] = value


def _normalize_label_key(label: str) -> str:
    raw = label.strip()
    if not raw:
        return ""
    arabic_map = {
        "الرقم المركزي": "central_number",
        "الرقم المركزى": "central_number",
        "شهادة مستخرج السجل التجاري": "document_title",
        "في الكويت": "issue_location",
        "العنوان التجاري": "company_address",
        "الكيان القانوني": "legal_entity_type",
        "رأس مال الشركة": "company_capital",
        "رقم الترخيص": "license_number",
        "بتاريخ": "registration_date",
        "رقم تحت بالسجل التجاري": "commercial_registry_number",
        "عدد الانشطة": "activity_count",
        "عدد الأنشطة": "activity_count",
        "عدد الشركاء": "partner_count",
        "حالة الترخيص الرئيسي": "license_status",
        "حالة الشركة": "company_status",
        "عدد المديرين": "managers_count",
        "الرقم المدني": "civil_number",
        "الرقم الالي للعنوان": "address_number",
        "الرقم الآلي للعنوان": "address_number",
        "المحافظة": "governorate",
        "المنطقة": "area",
        "القسيمة": "block",
        "الشارع": "street",
        "المبنى": "building",
        "الدور": "floor",
        "نوع الوحدة": "unit_type",
        "رقم الوحدة": "unit_number",
        "تاريخ الطباعة": "print_date",
        "اسم الشركة": "company_name",
    }
    candidates = [
        raw,
        raw.replace("_", " "),
        raw[::-1],
        raw[::-1].replace("_", " "),
        " ".join(reversed(raw.split())),
    ]
    for candidate in candidates:
        normalized = candidate.strip().lower()
        if not normalized:
            continue
        if normalized in arabic_map:
            return arabic_map[normalized]
        if normalized.isascii():
            return normalized.replace(" ", "_")
    normalized = raw.strip().lower()
    return normalized.replace(" ", "_")


def _sanitize_schema(schema: dict, max_fields: int = 15) -> dict:
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    cleaned: dict[str, dict] = {}
    for key, subschema in properties.items():
        normalized_key = _normalize_label_key(str(key))
        if not _is_valid_key(normalized_key):
            continue
        cleaned[normalized_key] = _sanitize_subschema(normalized_key, subschema)
        if len(cleaned) >= max_fields:
            break
    return {
        "type": "object",
        "properties": cleaned,
        "required": list(cleaned.keys()),
        "additionalProperties": False,
    }


def _sanitize_subschema(key: str, schema: object) -> dict:
    if isinstance(schema, dict):
        schema_type = schema.get("type")
        if schema_type == "array":
            if _array_key_is_plural(key):
                return {"type": "array", "items": {"type": "string"}}
            return {"type": "string"}
    return {"type": "string"}


def _is_valid_key(key: str) -> bool:
    if not key or len(key) > 40:
        return False
    if not key.isascii():
        return False
    for ch in key:
        if not (ch.islower() or ch.isdigit() or ch == "_"):
            return False
    return True


def _array_key_is_plural(key: str) -> bool:
    if "list" in key or "items" in key:
        return True
    if key.endswith("s") and not key.endswith(("ss", "us", "is")):
        return True
    if "list" in key or "items" in key:
        return True
    return False


def _count_array_fields(schema: dict) -> int:
    if not isinstance(schema, dict):
        return 0
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return 0
    count = 0
    for subschema in properties.values():
        if isinstance(subschema, dict) and subschema.get("type") == "array":
            count += 1
    return count
