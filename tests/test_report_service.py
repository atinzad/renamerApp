from dataclasses import dataclass
from datetime import datetime
from unittest.mock import Mock, patch

from app.domain.labels import Label
from app.domain.models import (
    AppliedRename,
    ExtractionRecord,
    FileRef,
    Job,
    LabelAssignment,
    LLMLabelClassification,
)
from app.services.report_service import ReportService


@dataclass
class FakeStorage:
    job: Job
    job_files: list[FileRef]
    applied_renames: dict[str, str]
    label_overrides: dict[str, str]
    label_assignments: dict[str, LabelAssignment]
    labels: dict[str, Label]
    llm_overrides: dict[str, str]
    llm_classifications: dict[str, LLMLabelClassification]
    extractions: dict[str, ExtractionRecord]

    def get_job(self, job_id: str) -> Job | None:
        if job_id != self.job.job_id:
            return None
        return self.job

    def get_latest_job(self) -> Job | None:
        return self.job

    def get_job_files_full(self, job_id: str) -> list[FileRef]:
        if job_id != self.job.job_id:
            return []
        return self.job_files

    def list_applied_renames(self, job_id: str) -> list[AppliedRename]:
        if job_id != self.job.job_id:
            return []
        return [
            AppliedRename(
                job_id=job_id,
                file_id=file_id,
                old_name="old",
                new_name=new_name,
                applied_at="2025-01-01T12:00:00+00:00",
            )
            for file_id, new_name in self.applied_renames.items()
        ]

    def get_file_timings(self, job_id: str, file_id: str):
        return None

    def get_extraction(self, job_id: str, file_id: str) -> ExtractionRecord | None:
        if job_id != self.job.job_id:
            return None
        return self.extractions.get(file_id)

    def get_file_label_override(self, job_id: str, file_id: str) -> str | None:
        if job_id != self.job.job_id:
            return None
        return self.label_overrides.get(file_id)

    def get_file_label_assignment(
        self, job_id: str, file_id: str
    ) -> LabelAssignment | None:
        if job_id != self.job.job_id:
            return None
        return self.label_assignments.get(file_id)

    def get_label(self, label_id: str) -> Label | None:
        return self.labels.get(label_id)

    def get_llm_label_override(self, job_id: str, file_id: str) -> str | None:
        if job_id != self.job.job_id:
            return None
        return self.llm_overrides.get(file_id)

    def get_llm_label_classification(
        self, job_id: str, file_id: str
    ) -> LLMLabelClassification | None:
        if job_id != self.job.job_id:
            return None
        return self.llm_classifications.get(file_id)


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
    storage = FakeStorage(
        job=job,
        job_files=job_files,
        applied_renames={"f1": "final-a.jpg"},
        label_overrides={},
        label_assignments={
            "f1": LabelAssignment(
                job_id=job.job_id,
                file_id="f1",
                label_id="label-1",
                status="MATCHED",
                score=0.9,
            )
        },
        labels={
            "label-1": Label(
                label_id="label-1",
                name="Invoice",
                is_active=True,
                created_at=job.created_at,
                extraction_schema_json="{}",
                naming_template="",
                llm="",
            )
        },
        llm_overrides={},
        llm_classifications={},
        extractions={},
    )
    drive = Mock()
    drive.upload_text_file.return_value = "report-file-123"

    service = ReportService(drive=drive, storage=storage)
    with patch(
        "app.services.time_utils.now_local_iso",
        return_value="2025-01-01T12:00:00+00:00",
    ):
        report_text = service.preview_report(job.job_id)
        assert "REPORT_VERSION: 2" in report_text
        assert "JOB_ID: job-123" in report_text
        assert "FINAL_NAME: final-a.jpg" in report_text
        assert "FINAL_LABEL: Invoice" in report_text

        report_file_id = service.write_report(job.job_id)
    assert report_file_id == "report-file-123"

    drive.upload_text_file.assert_called_once()
    args = drive.upload_text_file.call_args.args
    assert args[0] == "folder-abc"
    filename = args[1]
    content = args[2]
    assert filename.startswith("REPORT_") and filename.endswith(".txt")
    assert content == report_text


def test_preview_report_excludes_ocr_text() -> None:
    job = Job(
        job_id="job-123",
        folder_id="folder-abc",
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        status="CREATED",
    )
    job_files = [FileRef(file_id="f1", name="a.jpg", mime_type="image/jpeg")]
    storage = FakeStorage(
        job=job,
        job_files=job_files,
        applied_renames={},
        label_overrides={},
        label_assignments={},
        labels={},
        llm_overrides={},
        llm_classifications={},
        extractions={},
    )
    drive = Mock()

    service = ReportService(drive=drive, storage=storage)
    report_text = service.preview_report(job.job_id)

    assert "EXTRACTED_TEXT" not in report_text
    assert "EXTRACTED_FIELDS:\nunknown: UNKNOWN" in report_text


def test_preview_report_pretty_prints_fields() -> None:
    job = Job(
        job_id="job-123",
        folder_id="folder-abc",
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        status="CREATED",
    )
    job_files = [FileRef(file_id="f1", name="a.jpg", mime_type="image/jpeg")]
    storage = FakeStorage(
        job=job,
        job_files=job_files,
        applied_renames={},
        label_overrides={},
        label_assignments={},
        labels={},
        llm_overrides={},
        llm_classifications={},
        extractions={
            "f1": ExtractionRecord(
                job_id=job.job_id,
                file_id="f1",
                schema_json='{"name": "string", "items": "array"}',
                fields_json='{"name": "Acme", "items": ["A", "B"]}',
            )
        },
    )
    drive = Mock()

    service = ReportService(drive=drive, storage=storage)
    report_text = service.preview_report(job.job_id)

    assert "EXTRACTED_FIELDS:\nname: Acme\nitems: A, B" in report_text


def test_preview_report_parses_wrapped_fields_payload_and_json_schema() -> None:
    job = Job(
        job_id="job-123",
        folder_id="folder-abc",
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        status="CREATED",
    )
    job_files = [FileRef(file_id="f1", name="a.jpg", mime_type="image/jpeg")]
    storage = FakeStorage(
        job=job,
        job_files=job_files,
        applied_renames={},
        label_overrides={},
        label_assignments={},
        labels={},
        llm_overrides={},
        llm_classifications={},
        extractions={
            "f1": ExtractionRecord(
                job_id=job.job_id,
                file_id="f1",
                schema_json=(
                    '{"type":"object","properties":{"civil_id":{"type":"string"},'
                    '"birth_date":{"type":"string"}},"required":["civil_id","birth_date"],'
                    '"additionalProperties":false}'
                ),
                fields_json=(
                    '{"fields":{"civil_id":"123456789012","birth_date":"1995-08-07"},'
                    '"needs_review":false,"warnings":[]}'
                ),
            )
        },
    )
    drive = Mock()

    service = ReportService(drive=drive, storage=storage)
    report_text = service.preview_report(job.job_id)

    assert "EXTRACTED_FIELDS:\ncivil_id: 123456789012\nbirth_date: 1995-08-07" in report_text
    assert "type: UNKNOWN" not in report_text
    assert "properties: UNKNOWN" not in report_text
