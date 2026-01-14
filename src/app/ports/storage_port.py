from __future__ import annotations

from typing import Protocol

from app.domain.labels import Label, LabelExample
from app.domain.models import FileRef, Job, OCRResult, UndoLog


class StoragePort(Protocol):
    def create_job(self, folder_id: str) -> Job:
        """Create and persist a new job."""

    def get_job(self, job_id: str) -> Job | None:
        """Return a job by id, or None if missing."""

    def save_job_files(self, job_id: str, files: list[FileRef]) -> None:
        """Persist job file references."""

    def get_job_files(self, job_id: str) -> list[FileRef]:
        """Return file references for a job."""

    def save_undo_log(self, undo: UndoLog) -> None:
        """Persist an undo log entry."""

    def get_last_undo_log(self, job_id: str) -> UndoLog | None:
        """Return the most recent undo log for a job."""

    def clear_last_undo_log(self, job_id: str) -> None:
        """Remove the most recent undo log for a job."""

    def set_job_report_file_id(self, job_id: str, report_file_id: str) -> None:
        """Persist the report file id for a job."""

    def get_job_report_file_id(self, job_id: str) -> str | None:
        """Return the report file id for a job, if any."""

    def save_ocr_result(self, job_id: str, file_id: str, result: OCRResult) -> None:
        """Persist OCR output for a file."""

    def get_ocr_result(self, job_id: str, file_id: str) -> OCRResult | None:
        """Return OCR output for a file, if any."""

    def create_label(
        self, name: str, extraction_schema_json: str, naming_template: str
    ) -> Label:
        """Create and persist a label."""

    def deactivate_label(self, label_id: str) -> None:
        """Deactivate a label by id."""

    def list_labels(self, include_inactive: bool = False) -> list[Label]:
        """Return labels, optionally including inactive ones."""

    def get_label(self, label_id: str) -> Label | None:
        """Return a label by id, or None if missing."""

    def count_labels(self) -> int:
        """Return count of labels."""

    def attach_label_example(self, label_id: str, file_id: str, filename: str) -> LabelExample:
        """Attach a Drive file as an example for a label."""

    def list_label_examples(self, label_id: str) -> list[LabelExample]:
        """Return examples for a label."""

    def save_label_example_features(
        self,
        example_id: str,
        ocr_text: str,
        embedding: list[float] | None,
        token_fingerprint: set[str] | None,
    ) -> None:
        """Persist OCR text and similarity features for a label example."""

    def get_label_example_features(self, example_id: str) -> dict | None:
        """Return OCR text and features for a label example."""

    def upsert_file_label_assignment(
        self,
        job_id: str,
        file_id: str,
        label_id: str | None,
        score: float,
        status: str,
    ) -> None:
        """Persist a classification assignment for a job file."""

    def get_file_label_assignment(self, job_id: str, file_id: str) -> dict | None:
        """Return a classification assignment for a job file."""

    def list_file_label_assignments(self, job_id: str) -> list[dict]:
        """Return all classification assignments for a job."""

    def upsert_file_label_override(
        self, job_id: str, file_id: str, label_id: str | None
    ) -> None:
        """Persist a manual label override for a job file."""

    def get_file_label_override(self, job_id: str, file_id: str) -> dict | None:
        """Return a manual label override for a job file."""

    def list_file_label_overrides(self, job_id: str) -> list[dict]:
        """Return all label overrides for a job."""

    def bulk_insert_label_presets(self, labels: list[dict]) -> None:
        """Insert label presets in bulk."""

    def export_labels_for_presets(self) -> list[dict]:
        """Return label preset data for export."""
