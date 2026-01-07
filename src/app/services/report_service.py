from __future__ import annotations

from datetime import datetime

from app.domain.report_rendering import render_increment2_report
from app.ports.drive_port import DrivePort
from app.ports.storage_port import StoragePort


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
                "sort_index": index,
            }
            for index, file_ref in enumerate(job_files)
        ]
        generated_at_local_iso = self._local_now_iso()
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

    @staticmethod
    def _local_now_iso() -> str:
        return datetime.now().astimezone().isoformat()

    @staticmethod
    def _report_filename(created_at: datetime) -> str:
        if created_at.tzinfo is None:
            local_date = created_at.date()
        else:
            local_date = created_at.astimezone().date()
        return f"REPORT_{local_date.isoformat()}.txt"
