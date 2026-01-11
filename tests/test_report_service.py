import re
import unittest
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


class ReportServiceTests(unittest.TestCase):
    def test_preview_and_write_report(self) -> None:
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
        with patch.object(ReportService, "_local_now_iso", return_value="2025-01-01T12:00:00+00:00"):
            report_text = service.preview_report(job.job_id)
            self.assertIn("REPORT_VERSION: 1", report_text)
            self.assertIn("JOB_ID: job-123", report_text)

            report_file_id = service.write_report(job.job_id)
        self.assertEqual(report_file_id, "report-file-123")

        drive.upload_text_file.assert_called_once()
        args = drive.upload_text_file.call_args.args
        self.assertEqual(args[0], "folder-abc")
        filename = args[1]
        content = args[2]
        self.assertRegex(filename, r"^REPORT_\d{4}-\d{2}-\d{2}\.txt$")
        self.assertEqual(content, report_text)


if __name__ == "__main__":
    unittest.main()
