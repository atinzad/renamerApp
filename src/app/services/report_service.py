from __future__ import annotations

import json

from app.domain.report_v2 import FinalReportFileBlock, FinalReportModel, render_report_v2
from app.ports.drive_port import DrivePort
from app.ports.storage_port import StoragePort
from app.services.time_utils import local_date_yyyy_mm_dd, now_local_iso


class ReportService:
    def __init__(self, drive: DrivePort, storage: StoragePort) -> None:
        self._drive = drive
        self._storage = storage

    def preview_report(self, job_id: str | None = None) -> str:
        job = self._get_job_or_raise(job_id)
        job_files = self._storage.get_job_files_full(job.job_id)
        applied_renames = self._applied_renames_map(job.job_id)
        file_rows: list[dict] = []
        for index, file_ref in enumerate(job_files):
            final_name = applied_renames.get(file_ref.file_id, file_ref.name)
            fields, schema = self._get_extraction_payload(job.job_id, file_ref.file_id)
            timings = self._get_file_timings(job.job_id, file_ref.file_id)
            file_rows.append(
                {
                    "index": index,
                    "sort_index": file_ref.sort_index if file_ref.sort_index is not None else index,
                    "final_name": final_name,
                    "file_id": file_ref.file_id,
                    "final_label": self._get_final_label(job.job_id, file_ref.file_id),
                    "fields": fields,
                    "schema": schema,
                    "timings_ms": timings,
                }
            )
        ordered_files = sorted(
            file_rows,
            key=lambda item: (
                item["sort_index"],
                item["final_name"],
                item["file_id"],
            ),
        )
        blocks = [
            FinalReportFileBlock(
                index=index + 1,
                final_name=item["final_name"],
                file_id=item["file_id"],
                final_label=item["final_label"],
                extracted_fields=item["fields"],
                schema=item["schema"],
                timings_ms=item["timings_ms"],
            )
            for index, item in enumerate(ordered_files)
        ]
        generated_at_local_iso = now_local_iso()
        model = FinalReportModel(
            job_id=job.job_id,
            folder_id=job.folder_id,
            generated_at_local_iso=generated_at_local_iso,
            files=blocks,
        )
        return render_report_v2(model)

    def write_report(self, job_id: str | None = None) -> str:
        job = self._get_job_or_raise(job_id)
        content = self.preview_report(job.job_id)
        filename = self._report_filename(job.created_at)
        report_file_id = self._drive.upload_text_file(job.folder_id, filename, content)
        return report_file_id

    def get_final_report_summary(self, job_id: str | None = None) -> dict[str, int]:
        job = self._get_job_or_raise(job_id)
        job_files = self._storage.get_job_files_full(job.job_id)
        applied_renames = self._applied_renames_map(job.job_id)
        renamed_count = sum(
            1 for file_ref in job_files if file_ref.file_id in applied_renames
        )
        total_count = len(job_files)
        skipped_count = max(total_count - renamed_count, 0)
        needs_review_count = 0
        for file_ref in job_files:
            final_label = self._get_final_label(job.job_id, file_ref.file_id)
            assignment = self._storage.get_file_label_assignment(job.job_id, file_ref.file_id)
            status = assignment.status if assignment else None
            fields, schema = self._get_extraction_payload(job.job_id, file_ref.file_id)
            if final_label == "UNLABELED" or status == "AMBIGUOUS":
                needs_review_count += 1
                continue
            if self._fields_have_unknown(fields, schema):
                needs_review_count += 1
        return {
            "renamed": renamed_count,
            "skipped": skipped_count,
            "needs_review": needs_review_count,
            "total": total_count,
        }

    def _get_job_or_raise(self, job_id: str | None):
        if job_id is None:
            job = self._storage.get_latest_job()
        else:
            job = self._storage.get_job(job_id)
        if job is None:
            raise RuntimeError("Job not found.")
        return job

    @staticmethod
    def _report_filename(created_at) -> str:
        return f"REPORT_{local_date_yyyy_mm_dd(created_at)}.txt"

    def get_report_summary(self, job_id: str | None = None) -> dict[str, int]:
        return self.get_final_report_summary(job_id)

    def _get_extraction_payload(
        self, job_id: str, file_id: str
    ) -> tuple[dict | None, dict | None]:
        extraction = self._storage.get_extraction(job_id, file_id)
        if extraction is None:
            return self._fallback_fields_schema(None, None)
        fields_json = extraction.fields_json
        schema_json = extraction.schema_json
        fields_payload = self._load_json_dict(fields_json)
        fields = self._extract_fields(fields_payload)
        schema = self._load_json_dict(schema_json)
        return self._fallback_fields_schema(fields, schema)

    def _get_final_label(self, job_id: str, file_id: str) -> str:
        override_id = self._storage.get_file_label_override(job_id, file_id)
        if override_id:
            label = self._storage.get_label(override_id)
            if label is not None:
                return label.name
        assignment = self._storage.get_file_label_assignment(job_id, file_id)
        if assignment and assignment.label_id:
            label = self._storage.get_label(assignment.label_id)
            if label is not None:
                return label.name
        llm_override = self._storage.get_llm_label_override(job_id, file_id)
        if llm_override:
            return llm_override
        llm_classification = self._storage.get_llm_label_classification(job_id, file_id)
        label_name = llm_classification.label_name if llm_classification else None
        if label_name:
            return label_name
        return "UNLABELED"

    def _applied_renames_map(self, job_id: str) -> dict[str, str]:
        return {item.file_id: item.new_name for item in self._storage.list_applied_renames(job_id)}

    def _get_file_timings(self, job_id: str, file_id: str) -> dict[str, int | None]:
        record = self._storage.get_file_timings(job_id, file_id)
        if record is None:
            return {"ocr_ms": None, "classify_ms": None, "extract_ms": None}
        return {
            "ocr_ms": record.ocr_ms,
            "classify_ms": record.classify_ms,
            "extract_ms": record.extract_ms,
        }

    @staticmethod
    def _load_json_dict(value: str | None) -> dict | None:
        if not value:
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _fallback_fields_schema(
        fields: dict | None, schema: dict | None
    ) -> tuple[dict | None, dict | None]:
        if isinstance(schema, dict) and schema:
            keys = ReportService._schema_field_keys(schema)
            if not keys:
                keys = list(schema.keys())
            if not isinstance(fields, dict) or not fields:
                fields = {key: None for key in keys}
            else:
                fields = {key: fields.get(key) for key in keys}
            return fields, schema
        if not isinstance(fields, dict) or not fields:
            return {"unknown": None}, {"unknown": "string"}
        return fields, None

    @staticmethod
    def _fields_have_unknown(fields: dict | None, schema: dict | None) -> bool:
        if not isinstance(fields, dict) or not fields:
            return True
        if isinstance(schema, dict) and schema:
            keys = ReportService._schema_field_keys(schema)
            if not keys:
                keys = list(schema.keys())
        else:
            keys = list(fields.keys())
        for key in keys:
            value = fields.get(key)
            if value is None:
                return True
            if isinstance(value, str) and not value.strip():
                return True
            if isinstance(value, list) and not any(str(item).strip() for item in value):
                return True
            if isinstance(value, dict) and not value:
                return True
        return False

    @staticmethod
    def _extract_fields(value: dict | None) -> dict | None:
        if not isinstance(value, dict):
            return None
        if isinstance(value.get("fields"), dict):
            return value["fields"]
        return value

    @staticmethod
    def _schema_field_keys(schema: dict) -> list[str]:
        properties = schema.get("properties")
        if isinstance(properties, dict):
            return list(properties.keys())
        return list(schema.keys())
