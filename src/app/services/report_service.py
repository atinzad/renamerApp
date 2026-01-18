from __future__ import annotations

import json

from app.domain.report_rendering import render_increment2_report
from app.ports.drive_port import DrivePort
from app.ports.storage_port import StoragePort
from app.services.time_utils import local_date_yyyy_mm_dd, now_local_iso


class ReportService:
    def __init__(self, drive: DrivePort, storage: StoragePort) -> None:
        self._drive = drive
        self._storage = storage

    def preview_report(self, job_id: str) -> str:
        job = self._get_job_or_raise(job_id)
        job_files = self._storage.get_job_files(job_id)
        file_rows = [
            {
                "file_id": file_ref.file_id,
                "name": file_ref.name,
                "mime_type": file_ref.mime_type,
                "sort_index": file_ref.sort_index if file_ref.sort_index is not None else index,
                "extracted_text": self._get_extracted_text(job_id, file_ref.file_id),
                "extracted_fields": self._get_extracted_fields(job_id, file_ref.file_id),
            }
            for index, file_ref in enumerate(job_files)
        ]
        generated_at_local_iso = now_local_iso()
        return render_increment2_report(
            job_id=job.job_id,
            folder_id=job.folder_id,
            generated_at_local_iso=generated_at_local_iso,
            files=file_rows,
        )

    def write_report(self, job_id: str) -> str:
        job = self._get_job_or_raise(job_id)
        content = self.preview_report(job_id)
        filename = self._report_filename(job.created_at)
        report_file_id = self._drive.upload_text_file(job.folder_id, filename, content)
        return report_file_id

    def _get_job_or_raise(self, job_id: str):
        job = self._storage.get_job(job_id)
        if job is None:
            raise RuntimeError(f"Job not found: {job_id}")
        return job

    def _get_extracted_text(self, job_id: str, file_id: str) -> str:
        result = self._storage.get_ocr_result(job_id, file_id)
        if result is None or not result.text.strip():
            return ""
        return result.text

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

    @staticmethod
    def _report_filename(created_at) -> str:
        return f"REPORT_{local_date_yyyy_mm_dd(created_at)}.txt"
