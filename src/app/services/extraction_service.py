from __future__ import annotations

import json
from datetime import datetime, timezone
from time import perf_counter

from app.domain.extraction_models import GENERIC_MIN_SCHEMA
from app.domain.schema_utils import apply_missing_field_policy
from app.ports.llm_port import LLMPort
from app.ports.storage_port import StoragePort


class ExtractionService:
    def __init__(self, llm: LLMPort, storage: StoragePort) -> None:
        self._llm = llm
        self._storage = storage

    def extract_fields_for_job(self, job_id: str) -> None:
        files = self._ordered_files(job_id)
        for file_ref in files:
            self.extract_fields_for_file(job_id, file_ref.file_id)

    def extract_fields_for_file(self, job_id: str, file_id: str) -> None:
        started = perf_counter()
        schema, schema_warnings, instructions = self._resolve_schema(job_id, file_id)
        ocr_text = self._get_ocr_text(job_id, file_id)
        warnings: list[str] = list(schema_warnings)
        needs_review = False
        if self._is_empty_schema(schema):
            warnings.append("EMPTY_SCHEMA")
            needs_review = True
            extracted = {}
        elif not ocr_text:
            warnings.append("OCR_MISSING")
            needs_review = True
            extracted = {}
        else:
            extracted = self._llm.extract_fields(schema, ocr_text, instructions) or {}
        fields, missing_warnings, missing_review = apply_missing_field_policy(
            schema, extracted
        )
        warnings.extend(missing_warnings)
        needs_review = needs_review or missing_review
        payload = {
            "fields": fields,
            "needs_review": needs_review,
            "warnings": warnings,
        }
        updated_at = datetime.now(timezone.utc).isoformat()
        self._storage.save_extraction(
            job_id=job_id,
            file_id=file_id,
            schema_json=json.dumps(schema),
            fields_json=json.dumps(payload),
            confidences_json=json.dumps({}),
            updated_at=updated_at,
        )
        duration_ms = int((perf_counter() - started) * 1000)
        self._storage.upsert_file_timings(
            job_id=job_id,
            file_id=file_id,
            ocr_ms=None,
            classify_ms=None,
            extract_ms=duration_ms,
            updated_at_iso=updated_at,
        )

    def _resolve_schema(self, job_id: str, file_id: str) -> tuple[dict, list[str], str]:
        label_id = None
        warnings: list[str] = []
        instructions = ""
        override = self._storage.get_file_label_override(job_id, file_id)
        if override:
            label_id = override
        else:
            assignment = self._storage.get_file_label_assignment(job_id, file_id)
            if assignment and assignment.label_id:
                label_id = assignment.label_id
        if label_id:
            label = self._storage.get_label(label_id)
            if label and label.extraction_schema_json:
                schema = self._parse_schema(label.extraction_schema_json)
                if schema is not None:
                    instructions = label.extraction_instructions or ""
                    return schema, warnings, instructions
                warnings.append("INVALID_SCHEMA")
                return GENERIC_MIN_SCHEMA, warnings, self._default_instructions()
        return GENERIC_MIN_SCHEMA, warnings, self._default_instructions()

    @staticmethod
    def _parse_schema(value: str) -> dict | None:
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def _get_ocr_text(self, job_id: str, file_id: str) -> str:
        result = self._storage.get_ocr_result(job_id, file_id)
        if result is None or not result.text.strip():
            return ""
        return result.text

    @staticmethod
    def _is_empty_schema(schema: dict) -> bool:
        if not isinstance(schema, dict):
            return True
        if not schema:
            return True
        properties = schema.get("properties")
        if isinstance(properties, dict):
            return len(properties) == 0
        return False

    @staticmethod
    def _default_instructions() -> str:
        return 'Extract fields according to this schema. If a field is missing, return "UNKNOWN".'

    def _ordered_files(self, job_id: str) -> list:
        files = self._storage.get_job_files(job_id)
        return sorted(
            files,
            key=lambda item: (
                item.sort_index if item.sort_index is not None else 0,
                item.name,
                item.file_id,
            ),
        )
