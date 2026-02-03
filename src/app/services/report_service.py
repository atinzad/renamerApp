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
        job_files = self._get_job_files_full(job.job_id)
        applied_renames = self._applied_renames_map(job.job_id)
        file_rows: list[dict] = []
        for index, file_ref in enumerate(job_files):
            final_name = applied_renames.get(file_ref.file_id, file_ref.name)
            fields, schema = self._get_extraction_payload(job.job_id, file_ref.file_id)
            file_rows.append(
                {
                    "index": index,
                    "sort_index": file_ref.sort_index if file_ref.sort_index is not None else index,
                    "final_name": final_name,
                    "file_id": file_ref.file_id,
                    "final_label": self._get_final_label(job.job_id, file_ref.file_id),
                    "fields": fields,
                    "schema": schema,
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
        job_files = self._get_job_files_full(job.job_id)
        applied_renames = self._applied_renames_map(job.job_id)
        renamed_count = sum(
            1 for file_ref in job_files if file_ref.file_id in applied_renames
        )
        total_count = len(job_files)
        skipped_count = max(total_count - renamed_count, 0)
        needs_review_count = 0
        for file_ref in job_files:
            final_label = self._get_final_label(job.job_id, file_ref.file_id)
            assignment = self._get_label_assignment(job.job_id, file_ref.file_id)
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

    def get_report_summary(self, job_id: str | None = None) -> dict[str, int]:
        return self.get_final_report_summary(job_id)

    def _get_extraction_payload(
        self, job_id: str, file_id: str
    ) -> tuple[dict | None, dict | None]:
        extraction = self._storage.get_extraction(job_id, file_id)
        if extraction is None:
            return self._fallback_fields_schema(None, None)
        fields_json = self._extract_value(extraction, "fields_json")
        schema_json = self._extract_value(extraction, "schema_json")
        fields = self._load_json_dict(fields_json)
        schema = self._load_json_dict(schema_json)
        return self._fallback_fields_schema(fields, schema)

    def _get_final_label(self, job_id: str, file_id: str) -> str:
        override_id = self._get_override_label_id(job_id, file_id)
        if override_id:
            label = self._storage.get_label(override_id)
            if label is not None:
                return label.name
        assignment = self._get_label_assignment(job_id, file_id)
        if assignment and assignment.label_id:
            label = self._storage.get_label(assignment.label_id)
            if label is not None:
                return label.name
        llm_override = self._storage.get_llm_label_override(job_id, file_id)
        if llm_override:
            return llm_override
        llm_classification = self._storage.get_llm_label_classification(job_id, file_id)
        label_name = self._extract_llm_label_name(llm_classification)
        if label_name:
            return label_name
        return "UNLABELED"

    def _applied_renames_map(self, job_id: str) -> dict[str, str]:
        return {
            self._extract_value(item, "file_id"): self._extract_value(item, "new_name")
            for item in self._storage.list_applied_renames(job_id)
        }

    def _get_override_label_id(self, job_id: str, file_id: str) -> str | None:
        override = self._storage.get_file_label_override(job_id, file_id)
        if isinstance(override, str):
            return override
        return self._extract_value(override, "label_id") if override else None

    def _get_label_assignment(self, job_id: str, file_id: str):
        assignment = self._storage.get_file_label_assignment(job_id, file_id)
        if assignment is None:
            return None
        if isinstance(assignment, tuple) and len(assignment) >= 3:
            return _LabelAssignmentShim(
                label_id=assignment[0],
                status=str(assignment[2]),
                score=float(assignment[1]) if assignment[1] is not None else 0.0,
            )
        label_id = self._extract_value(assignment, "label_id")
        status = self._extract_value(assignment, "status")
        score = self._extract_value(assignment, "score")
        return _LabelAssignmentShim(
            label_id=label_id,
            status=status or "",
            score=float(score) if score is not None else 0.0,
        )

    def _extract_llm_label_name(self, classification) -> str | None:
        if classification is None:
            return None
        if isinstance(classification, tuple) and classification:
            return classification[0]
        return self._extract_value(classification, "label_name")

    def _get_job_files_full(self, job_id: str):
        getter = getattr(self._storage, "get_job_files_full", None)
        if callable(getter):
            return getter(job_id)
        return self._storage.get_job_files(job_id)

    @staticmethod
    def _extract_value(item, key: str):
        if isinstance(item, dict):
            return item.get(key)
        return getattr(item, key, None)

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
            if not isinstance(fields, dict) or not fields:
                fields = {key: None for key in schema.keys()}
            return fields, schema
        if not isinstance(fields, dict) or not fields:
            return {"unknown": None}, {"unknown": "string"}
        return fields, None

    @staticmethod
    def _fields_have_unknown(fields: dict | None, schema: dict | None) -> bool:
        if not isinstance(fields, dict) or not fields:
            return True
        keys = list(schema.keys()) if isinstance(schema, dict) and schema else list(fields.keys())
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


class _LabelAssignmentShim:
    def __init__(self, label_id: str | None, status: str, score: float) -> None:
        self.label_id = label_id
        self.status = status
        self.score = score

    @staticmethod
    def _report_filename(created_at) -> str:
        return f"REPORT_{local_date_yyyy_mm_dd(created_at)}.txt"
