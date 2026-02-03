from __future__ import annotations

import json

from app.domain.report_rendering import render_increment7_report
from app.ports.drive_port import DrivePort
from app.ports.storage_port import StoragePort
from app.services.time_utils import local_date_yyyy_mm_dd, now_local_iso


class ReportService:
    def __init__(self, drive: DrivePort, storage: StoragePort) -> None:
        self._drive = drive
        self._storage = storage

    def preview_report(self, job_id: str | None = None) -> str:
        job = self._get_job_or_raise(job_id)
        job_files = self._storage.get_job_files(job.job_id)
        applied_renames = self._applied_renames_map(job.job_id)
        file_rows = [
            {
                "file_id": file_ref.file_id,
                "final_name": applied_renames.get(file_ref.file_id, file_ref.name),
                "sort_index": file_ref.sort_index if file_ref.sort_index is not None else index,
                "final_label": self._get_final_label(job.job_id, file_ref.file_id),
                "extracted_fields": self._get_extracted_fields(job.job_id, file_ref.file_id),
                "field_order": self._get_extraction_field_order(job.job_id, file_ref.file_id),
            }
            for index, file_ref in enumerate(job_files)
        ]
        generated_at_local_iso = now_local_iso()
        return render_increment7_report(
            job_id=job.job_id,
            folder_id=job.folder_id,
            generated_at_local_iso=generated_at_local_iso,
            files=file_rows,
        )

    def write_report(self, job_id: str | None = None) -> str:
        job = self._get_job_or_raise(job_id)
        content = self.preview_report(job.job_id)
        filename = self._report_filename(job.created_at)
        report_file_id = self._drive.upload_text_file(job.folder_id, filename, content)
        return report_file_id

    def get_report_summary(self, job_id: str | None = None) -> dict[str, int]:
        job = self._get_job_or_raise(job_id)
        job_files = self._storage.get_job_files(job.job_id)
        applied_renames = self._applied_renames_map(job.job_id)
        renamed_count = sum(
            1 for file_ref in job_files if file_ref.file_id in applied_renames
        )
        total_count = len(job_files)
        skipped_count = max(total_count - renamed_count, 0)
        needs_review_count = 0
        for file_ref in job_files:
            assignment = self._storage.get_file_label_assignment_summary(
                job.job_id, file_ref.file_id
            )
            if assignment is None:
                needs_review_count += 1
                continue
            status = assignment[2]
            final_label = self._get_final_label(job.job_id, file_ref.file_id)
            if status in {"AMBIGUOUS", "NO_MATCH"} or final_label == "UNLABELED":
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

    def _get_extracted_fields(self, job_id: str, file_id: str) -> dict | None:
        extraction = self._storage.get_extraction(job_id, file_id)
        if extraction is None:
            return None
        fields_json = extraction.get("fields_json")
        if not fields_json:
            return None
        try:
            return json.loads(fields_json)
        except json.JSONDecodeError:
            return None

    def _get_extraction_field_order(self, job_id: str, file_id: str) -> list[str] | None:
        extraction = self._storage.get_extraction(job_id, file_id)
        if extraction is None:
            return None
        schema_json = extraction.get("schema_json")
        if not schema_json:
            return None
        try:
            schema = json.loads(schema_json)
        except json.JSONDecodeError:
            return None
        if isinstance(schema, dict):
            return list(schema.keys())
        return None

    def _get_final_label(self, job_id: str, file_id: str) -> str:
        override = self._storage.get_file_label_override_id(job_id, file_id)
        if override:
            label = self._storage.get_label(override)
            if label is not None:
                return label.name
        assignment = self._storage.get_file_label_assignment_summary(job_id, file_id)
        if assignment is not None:
            label_id = assignment[0]
            if label_id:
                label = self._storage.get_label(label_id)
                if label is not None:
                    return label.name
        llm_override = self._storage.get_llm_label_override(job_id, file_id)
        if llm_override:
            return llm_override
        llm_classification = self._storage.get_llm_label_classification(job_id, file_id)
        if llm_classification:
            label_name, _, _ = llm_classification
            if label_name:
                return label_name
        return "UNLABELED"

    def _applied_renames_map(self, job_id: str) -> dict[str, str]:
        return {
            item["file_id"]: item["new_name"]
            for item in self._storage.list_applied_renames(job_id)
        }

    @staticmethod
    def _report_filename(created_at) -> str:
        return f"REPORT_{local_date_yyyy_mm_dd(created_at)}.txt"
