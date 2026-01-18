from dataclasses import dataclass
from datetime import datetime
from unittest.mock import Mock, patch

from app.domain.models import FileRef, Job, OCRResult
from app.services.report_service import ReportService


@dataclass
class FakeStorage:
    job: Job
    job_files: list[FileRef]
    ocr_results: dict[str, OCRResult]

    def get_job(self, job_id: str) -> Job | None:
        if job_id != self.job.job_id:
            return None
        return self.job

    def get_job_files(self, job_id: str) -> list[FileRef]:
        if job_id != self.job.job_id:
            return []
        return self.job_files

    def get_ocr_result(self, job_id: str, file_id: str) -> OCRResult | None:
        if job_id != self.job.job_id:
            return None
        return self.ocr_results.get(file_id)

    def get_extraction(self, job_id: str, file_id: str) -> dict | None:
        return None


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
    storage = FakeStorage(job=job, job_files=job_files, ocr_results={})
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


def test_preview_report_uses_ocr_text() -> None:
    job = Job(
        job_id="job-123",
        folder_id="folder-abc",
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        status="CREATED",
    )
    job_files = [FileRef(file_id="f1", name="a.jpg", mime_type="image/jpeg")]
    ocr_results = {"f1": OCRResult(text="OCR content", confidence=0.5)}
    storage = FakeStorage(job=job, job_files=job_files, ocr_results=ocr_results)
    drive = Mock()

    service = ReportService(drive=drive, storage=storage)
    report_text = service.preview_report(job.job_id)

    assert "EXTRACTED_TEXT:\nOCR content" in report_text


def test_preview_report_mixes_ocr_and_placeholder() -> None:
    job = Job(
        job_id="job-123",
        folder_id="folder-abc",
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        status="CREATED",
    )
    job_files = [
        FileRef(file_id="f1", name="a.jpg", mime_type="image/jpeg"),
        FileRef(file_id="f2", name="b.jpg", mime_type="image/jpeg"),
    ]
    ocr_results = {"f1": OCRResult(text="OCR content", confidence=None)}
    storage = FakeStorage(job=job, job_files=job_files, ocr_results=ocr_results)
    drive = Mock()

    service = ReportService(drive=drive, storage=storage)
    report_text = service.preview_report(job.job_id)

    assert "EXTRACTED_TEXT:\nOCR content" in report_text
    assert "EXTRACTED_TEXT:\n<<<PENDING_EXTRACTION>>>" in report_text
