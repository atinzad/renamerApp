from __future__ import annotations

import json
import re

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
        user_guidance = (guidance_override or "").strip()
        schema_request = {
            "type": "object",
            "properties": {
                "schema": {"type": "object"},
                "instructions": {"type": "string"},
            },
            "required": ["schema", "instructions"],
            "additionalProperties": False,
        }
        if user_guidance:
            schema, instructions = self._build_from_guidance_only(
                user_guidance, schema_request
            )
            self._storage.update_label_extraction_schema(label_id, json.dumps(schema))
            self._storage.update_label_extraction_instructions(label_id, instructions)
            return schema, instructions
        if not ocr_text.strip():
            raise ValueError("OCR text is required.")
        ocr_context = _build_ocr_schema_context(ocr_text)
        if not ocr_context.strip():
            ocr_context = ocr_text
        guidance = (
            "Generate a document extraction JSON schema from OCR context. "
            "Do not copy OCR noise or random tokens as field names. "
            "Prefer fields that are relevant to official/business documents: "
            "name, address, ID/number, date, status, amount, parties, and registry/license metadata. "
            "Use concise English snake_case keys only. Limit the schema to at most 15 fields. "
            "The schema must be a JSON schema object with type, properties, required, and "
            "additionalProperties=false. Use boolean only for true/false flags; otherwise use string. "
            "Use arrays only for clear repeated entities (people/items/activities). "
            "If OCR is noisy, infer likely business-relevant fields instead of literal gibberish labels. "
            "Include a brief 'description' for each field explaining what value to extract "
            "and its expected format (e.g., 'DD/MM/YYYY date', '12-digit number')."
        )
        refine_guidance = (
            "Review the proposed schema and refine it using OCR context. "
            "Keep only document-relevant fields and remove noisy OCR artifacts. "
            "Array fields must use plural names; singular fields must not be arrays. "
            "Ensure no more than 15 fields. Output concise English snake_case keys. "
            "Preserve field descriptions. If missing, add brief descriptions."
        )
        example = self._ocr_text_to_example(ocr_context)
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
            ocr_context,
            f"{guidance} {detected_hint}",
        )
        if schema is None:
            schema, instructions = self._fallback_schema(ocr_context)
        schema = _sanitize_schema(schema, max_fields=15)
        refinement_payload = (
            "OCR context:\n"
            f"{ocr_context}\n\n"
            "Proposed schema JSON:\n"
            f"{json.dumps(schema)}"
        )
        schema, _ = self._attempt_llm_schema(
            schema_request,
            refinement_payload,
            f"{refine_guidance} {detected_hint}",
        )
        schema = _sanitize_schema(schema or {}, max_fields=15)
        if _count_array_fields(schema) > 3:
            retry_guidance = (
                f"{guidance} Avoid arrays unless the OCR clearly lists multiple entries."
            )
            schema, instructions = self._attempt_llm_schema(
                schema_request,
                ocr_context,
                f"{retry_guidance} {detected_hint}",
            )
            if schema is None:
                schema, instructions = self._fallback_schema(ocr_context)
            schema = _sanitize_schema(schema or {}, max_fields=15)
        if not schema.get("properties"):
            retry_guidance = (
                f"{guidance} Return only the 10-15 most important fields. "
                "Avoid noisy OCR artifacts and make reasonable assumptions about core fields."
            )
            schema, instructions = self._attempt_llm_schema(
                schema_request,
                ocr_context,
                f"{retry_guidance} {detected_hint}",
            )
            if schema is None:
                schema, instructions = self._fallback_schema(ocr_context)
            schema = _sanitize_schema(schema or {}, max_fields=15)
        if not schema.get("properties"):
            schema = _default_relevant_schema()
        instructions = build_instruction_from_example(schema)
        instructions = _apply_instruction_guidance(
            instructions, user_guidance, schema
        )
        self._storage.update_label_extraction_schema(label_id, json.dumps(schema))
        self._storage.update_label_extraction_instructions(label_id, instructions)
        return schema, instructions

    def _build_from_guidance_only(
        self, user_guidance: str, schema_request: dict
    ) -> tuple[dict, str]:
        explicit_fields = _extract_guidance_fields(user_guidance)
        schema: dict | None
        if explicit_fields:
            schema = _schema_from_guidance_fields(explicit_fields, user_guidance)
        else:
            guidance_prompt = (
                "Generate a JSON schema and concise extraction instructions using ONLY user guidance. "
                "Ignore OCR text entirely. "
                "Use concise English snake_case keys only. "
                "Limit schema to at most 15 document-relevant fields. "
                "Return a JSON schema object with type, properties, required, and additionalProperties=false. "
                "Include a brief 'description' for each field explaining what value to extract "
                "and its expected format (e.g., 'DD/MM/YYYY date', '12-digit number')."
            )
            schema, _ = self._attempt_llm_schema(
                schema_request,
                f"User guidance:\n{user_guidance}",
                guidance_prompt,
            )
        schema = _sanitize_schema(schema or {}, max_fields=15)
        if explicit_fields:
            schema = _apply_allowed_fields_constraint(
                schema, explicit_fields, max_fields=15
            )
        if not schema.get("properties"):
            fallback_fields = explicit_fields or _extract_guidance_fields(
                f"Extract {user_guidance}"
            )
            if fallback_fields:
                schema = _schema_from_guidance_fields(fallback_fields, user_guidance)
            else:
                schema = _default_relevant_schema()
        instructions = build_instruction_from_example(schema)
        instructions = _apply_instruction_guidance(
            instructions, user_guidance, schema
        )
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
                if normalized and _is_reasonable_key(normalized):
                    _append_example_value(example, normalized, value)
                last_value_line = value or last_value_line
                continue
            if raw_line.lstrip().startswith(":"):
                label = raw_line.lstrip()[1:].strip()
                normalized = _normalize_label_key(label)
                if normalized and _is_reasonable_key(normalized) and last_value_line:
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
    scored: list[tuple[float, str, dict]] = []
    for key, subschema in properties.items():
        normalized_key = _normalize_label_key(str(key))
        if not _is_valid_key(normalized_key):
            continue
        if not _is_reasonable_key(normalized_key):
            continue
        cleaned_subschema = _sanitize_subschema(normalized_key, subschema)
        score = _field_relevance_score(normalized_key)
        scored.append((score, normalized_key, cleaned_subschema))
    scored.sort(key=lambda item: (-item[0], item[1]))
    cleaned: dict[str, dict] = {}
    for _score, key, subschema in scored:
        cleaned[key] = subschema
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
        desc = schema.get("description")
        base: dict
        if schema_type in {"string", "boolean", "number", "integer"}:
            base = {"type": schema_type}
        elif schema_type == "array":
            if _array_key_is_plural(key):
                base = {"type": "array", "items": {"type": "string"}}
            else:
                base = {"type": "string"}
        else:
            base = {"type": "string"}
        if isinstance(desc, str) and desc.strip():
            base["description"] = desc.strip()
        return base
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


def _is_reasonable_key(key: str) -> bool:
    if not key or key.startswith("_") or key.endswith("_"):
        return False
    if key.isdigit():
        return False
    if "__" in key:
        return False
    tokens = [token for token in key.split("_") if token]
    if not tokens:
        return False
    if not any(any(ch.isalpha() for ch in token) for token in tokens):
        return False
    short_tokens = [token for token in tokens if len(token) <= 2]
    if (
        len(short_tokens) / len(tokens) >= 0.5
        and key not in {"id", "no", "iban", "vat", "tin", "dob", "ssn"}
    ):
        return False
    if len(tokens) == 1 and len(tokens[0]) <= 4 and _field_relevance_score(key) <= 0:
        return False
    return _field_relevance_score(key) >= 0


def _field_relevance_score(key: str) -> float:
    positive_terms = {
        "name",
        "address",
        "id",
        "number",
        "date",
        "birth",
        "expiry",
        "expiration",
        "issue",
        "status",
        "amount",
        "value",
        "total",
        "owner",
        "company",
        "license",
        "registry",
        "document",
        "civil",
        "passport",
        "signature",
        "iban",
        "bank",
        "account",
        "phone",
        "email",
        "country",
        "city",
        "street",
        "building",
        "floor",
        "unit",
        "nationality",
        "gender",
        "type",
        "party",
        "parties",
    }
    negative_terms = {
        "raw",
        "ocr",
        "preprocessed",
        "text",
        "line",
        "page",
        "subnet",
        "hist",
        "tmp",
    }
    score = 0.0
    tokens = [token for token in key.split("_") if token]
    if not tokens:
        return -10.0
    for token in tokens:
        if token in positive_terms:
            score += 3.0
        if token in negative_terms:
            score -= 2.5
        if len(token) == 1 and token.isalpha():
            score -= 2.0
        if token.isdigit():
            score -= 2.0
    if key.endswith(("_id", "_number", "_date", "_name", "_address", "_status")):
        score += 1.5
    if len(tokens) > 5:
        score -= 1.5
    return score


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


def _extract_only_include_fields(guidance: str) -> list[str]:
    if not guidance:
        return []
    patterns = [
        r"\bonly include\b(?P<fields>[^.;\n]+)",
        r"\binclude only\b(?P<fields>[^.;\n]+)",
        r"\blimit(?:\s+the\s+schema|\s+fields)?\s+to\b(?P<fields>[^.;\n]+)",
        r"\brestrict(?:\s+the\s+schema|\s+fields)?\s+to\b(?P<fields>[^.;\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, guidance, flags=re.IGNORECASE)
        if not match:
            continue
        return _parse_guidance_field_names(match.group("fields"))
    return []


def _parse_guidance_field_names(value: str) -> list[str]:
    normalized_value = value.replace("\n", " ")
    normalized_value = re.sub(r"\b(and|or)\b", ",", normalized_value, flags=re.IGNORECASE)
    parts = re.split(r"[,/|]", normalized_value)
    fields: list[str] = []
    seen: set[str] = set()
    for raw_part in parts:
        candidate = raw_part.strip(" .:;\"'`[](){}")
        candidate = re.sub(r"^(?:the|a|an)\s+", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\bfields?\b$", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(
            r"^(?:see\s+if|check\s+if|whether|if)\s+",
            "",
            candidate,
            flags=re.IGNORECASE,
        )
        if not candidate:
            continue
        field_name = _normalize_label_key(candidate)
        field_name = _coerce_candidate_to_core_field(candidate, field_name)
        field_name = _canonicalize_guidance_key(field_name)
        if not _is_valid_key(field_name):
            continue
        if field_name in seen:
            continue
        seen.add(field_name)
        fields.append(field_name)
    return fields


def _apply_allowed_fields_constraint(
    schema: dict, allowed_fields: list[str], max_fields: int = 15
) -> dict:
    if not allowed_fields:
        return schema
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    if not isinstance(properties, dict):
        properties = {}
    constrained: dict[str, dict] = {}
    for field_name in allowed_fields[:max_fields]:
        candidate_schema = properties.get(field_name, {"type": "string"})
        constrained[field_name] = _sanitize_subschema(field_name, candidate_schema)
    return {
        "type": "object",
        "properties": constrained,
        "required": list(constrained.keys()),
        "additionalProperties": False,
    }


def _looks_restrictive(guidance: str) -> bool:
    return bool(
        re.search(
            r"\b(nothing else|anything else|no other fields?|and nothing else|only these fields?)\b",
            guidance,
            flags=re.IGNORECASE,
        )
    )


def _canonicalize_guidance_key(field_name: str) -> str:
    alias_map = {
        "civil_id_number": "civil_number",
        "civil_id_no": "civil_number",
        "civil_id": "civil_number",
        "civilid": "civil_number",
        "civil_no": "civil_number",
        "expiry": "expiry_date",
        "expiration": "expiry_date",
        "expiration_date": "expiry_date",
        "date_of_expiry": "expiry_date",
        "full_name": "name",
        "residential_address": "address",
        "home_address": "address",
        "postal_address": "address",
        "signature": "signature_present",
        "signature_filled": "signature_present",
        "signature_available": "signature_present",
        "signature_present_flag": "signature_present",
    }
    return alias_map.get(field_name, field_name)


def _coerce_candidate_to_core_field(candidate: str, normalized: str) -> str:
    lowered = candidate.strip().lower()
    if "signature" in lowered:
        return "signature_present"
    if "civil" in lowered and "id" in lowered:
        return "civil_id"
    if "iban" in lowered:
        return "iban"
    if lowered in {"address", "the address"}:
        return "address"
    if "expiry" in lowered or "expiration" in lowered:
        return "expiry_date"
    if lowered in {"name", "full name", "the name"}:
        return "name"
    return normalized


def _extract_guidance_fields(guidance: str) -> list[str]:
    if not guidance:
        return []
    explicit = _extract_only_include_fields(guidance)
    if explicit:
        return explicit
    action_patterns = [
        r"\bextract\b(?P<fields>[^.\n;]+)",
        r"\breturn\b(?P<fields>[^.\n;]+)",
        r"\boutput\b(?P<fields>[^.\n;]+)",
        r"\bcapture\b(?P<fields>[^.\n;]+)",
    ]
    for pattern in action_patterns:
        match = re.search(pattern, guidance, flags=re.IGNORECASE)
        if not match:
            continue
        parsed = _parse_guidance_field_names(match.group("fields"))
        if parsed:
            return parsed
    if _looks_restrictive(guidance):
        parsed = _parse_guidance_field_names(guidance)
        if parsed:
            return parsed
    return []


_FIELD_DESCRIPTIONS: dict[str, str] = {
    "civil_number": "Civil ID number as printed on the card",
    "name": "Full name as it appears on the document",
    "expiry_date": "Expiry/expiration date",
    "issue_date": "Issue date",
    "date_of_birth": "Date of birth",
    "address": "Full address",
    "nationality": "Nationality",
    "gender": "Gender (Male/Female)",
    "document_number": "Document reference number",
    "iban": "IBAN bank account number",
    "company_name": "Company or organization name",
    "commercial_registry_number": "Commercial registry number",
    "license_number": "License number",
    "phone": "Phone number",
    "email": "Email address",
    "signature_present": "Whether a signature is present (true/false)",
}


def _schema_from_guidance_fields(fields: list[str], guidance: str) -> dict:
    properties: dict[str, dict] = {}
    for field_name in fields[:15]:
        prop = _infer_guidance_field_schema(field_name, guidance)
        desc = _FIELD_DESCRIPTIONS.get(field_name)
        if desc:
            prop["description"] = desc
        properties[field_name] = prop
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties.keys()),
        "additionalProperties": False,
    }


def _infer_guidance_field_schema(field_name: str, guidance: str) -> dict:
    lowered_guidance = guidance.lower()
    boolean_hint = any(
        marker in lowered_guidance
        for marker in [
            "true or false",
            "boolean",
            "yes or no",
            "yes/no",
            "flag",
            "filled or not",
            "present or not",
        ]
    )
    boolean_field_hint = (
        field_name.startswith(("is_", "has_"))
        or field_name.endswith(("_flag", "_present", "_available"))
        or "signature" in field_name
    )
    if boolean_hint and boolean_field_hint:
        return {"type": "boolean"}
    return {"type": "string"}


def _build_ocr_schema_context(
    ocr_text: str, max_lines: int = 220, max_chars: int = 14000
) -> str:
    lines = [line.strip() for line in ocr_text.splitlines()]
    selected: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if not line:
            continue
        normalized = re.sub(r"\s+", " ", line).strip()
        if not normalized or normalized in seen:
            continue
        if not _is_meaningful_ocr_line(normalized):
            continue
        is_label_like = ":" in normalized or len(normalized.split()) <= 8
        if not is_label_like and len(selected) > max_lines // 3:
            continue
        selected.append(normalized)
        seen.add(normalized)
        if len(selected) >= max_lines:
            break
        if sum(len(item) + 1 for item in selected) >= max_chars:
            break
    if not selected:
        fallback: list[str] = []
        for line in lines:
            normalized = re.sub(r"\s+", " ", line).strip()
            if not normalized:
                continue
            if not _is_meaningful_ocr_line(normalized):
                continue
            fallback.append(normalized)
            if len(fallback) >= 80:
                break
        selected = fallback
    context = "\n".join(selected)
    if len(context) > max_chars:
        context = context[:max_chars]
    return context


def _is_meaningful_ocr_line(line: str) -> bool:
    lowered = line.lower()
    if lowered.startswith(("preprocessed_ocr", "raw_ocr")):
        return False
    alpha_or_digit = sum(
        ch.isdigit() or ch.isalpha() or ("\u0600" <= ch <= "\u06FF") for ch in line
    )
    if alpha_or_digit < 3:
        return False
    symbols = sum(not ch.isalnum() and not ch.isspace() for ch in line)
    if symbols > 0 and symbols / max(1, len(line)) > 0.45:
        return False
    if len(line) > 180 and ":" not in line:
        return False
    return True


def _default_relevant_schema() -> dict:
    properties = {
        "document_number": {"type": "string"},
        "name": {"type": "string"},
        "address": {"type": "string"},
        "issue_date": {"type": "string"},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties.keys()),
        "additionalProperties": False,
    }


def _apply_instruction_guidance(
    instructions: str, user_guidance: str, schema: dict
) -> str:
    if not _guidance_requests_pattern_inference(user_guidance):
        return instructions
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    field_names = list(properties.keys()) if isinstance(properties, dict) else []
    field_list = ", ".join(field_names)
    if field_list:
        guidance_line = (
            "When labels are noisy, infer values using text patterns for these fields: "
            f"{field_list}."
        )
    else:
        guidance_line = (
            "When labels are noisy, infer values using text patterns for requested fields."
        )
    if guidance_line in instructions:
        return instructions
    if instructions.strip():
        return f"{instructions.strip()} {guidance_line}"
    return guidance_line


def _guidance_requests_pattern_inference(user_guidance: str) -> bool:
    if not user_guidance:
        return False
    return bool(
        re.search(
            r"\b(detect|infer|use)\b.*\bpattern",
            user_guidance,
            flags=re.IGNORECASE,
        )
    )
