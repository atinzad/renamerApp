from dataclasses import dataclass
from datetime import datetime
from unittest.mock import Mock, patch

from app.domain.models import FileRef, Job
from app.services.report_service import ReportService


@dataclass
class FakeStorage:
    job: Job
    job_files: list[FileRef]

    def get_job(self, job_id: str) -> Job | None:
        if job_id != self.job.job_id:
            return None
        return self.job

    def get_job_files(self, job_id: str) -> list[FileRef]:
        if job_id != self.job.job_id:
            return []
        return self.job_files


def test_preview_and_write_report() -> None:
    job = Job(
        job_id="job-123",
        folder_id="folder-abc",
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        status="CREATED",
    )
    job_files = [
        FileRef(file_id="f1", name="a.jpg", mime_type="image/jpeg"),
        FileRef(file_id="f2", name="b.png", mime_type="image/png"),
    ]
    storage = FakeStorage(job=job, job_files=job_files)
    drive = Mock()
    drive.upload_text_file.return_value = "report-file-123"

    service = ReportService(drive=drive, storage=storage)
    with patch(
        "app.services.time_utils.now_local_iso",
        return_value="2025-01-01T12:00:00+00:00",
    ):
        report_text = service.preview_report(job.job_id)
        assert "REPORT_VERSION: 1" in report_text
        assert "JOB_ID: job-123" in report_text

        report_file_id = service.write_report(job.job_id)
    assert report_file_id == "report-file-123"

    drive.upload_text_file.assert_called_once()
    args = drive.upload_text_file.call_args.args
    assert args[0] == "folder-abc"
    filename = args[1]
    content = args[2]
    assert filename.startswith("REPORT_") and filename.endswith(".txt")
    assert content == report_text
