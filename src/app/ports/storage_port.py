from __future__ import annotations

from typing import Protocol

from app.domain.doc_types import DocType, DocTypeClassification
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

    def update_label_extraction_instructions(
        self, label_id: str, instructions: str
    ) -> None:
        """Update extraction instructions for a label."""

    def update_label_llm(self, label_id: str, llm: str) -> None:
        """Update LLM label instructions for a label."""

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

    def delete_label_example(self, example_id: str) -> None:
        """Delete a label example and its stored features."""

    def delete_label(self, label_id: str) -> None:
        """Delete a label and any related references."""

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

    def upsert_doc_type_classification(
        self,
        job_id: str,
        file_id: str,
        classification: DocTypeClassification,
        updated_at_iso: str,
    ) -> None:
        """Persist a doc type classification for a job file."""

    def get_doc_type_classification(
        self, job_id: str, file_id: str
    ) -> DocTypeClassification | None:
        """Return a doc type classification for a job file."""

    def list_doc_type_classifications(
        self, job_id: str
    ) -> dict[str, DocTypeClassification]:
        """Return doc type classifications for a job keyed by file_id."""

    def set_doc_type_override(
        self, job_id: str, file_id: str, doc_type: DocType, updated_at_iso: str
    ) -> None:
        """Persist a doc type override for a job file."""

    def get_doc_type_override(self, job_id: str, file_id: str) -> DocType | None:
        """Return a doc type override for a job file."""

    def list_doc_type_overrides(self, job_id: str) -> dict[str, DocType]:
        """Return doc type overrides for a job keyed by file_id."""

    def upsert_llm_label_classification(
        self,
        job_id: str,
        file_id: str,
        label_name: str | None,
        confidence: float,
        signals: list[str],
        updated_at_iso: str,
    ) -> None:
        """Persist an LLM label fallback classification for a job file."""

    def get_llm_label_classification(
        self, job_id: str, file_id: str
    ) -> tuple[str | None, float, list[str]] | None:
        """Return an LLM label fallback classification for a job file."""

    def list_llm_label_classifications(
        self, job_id: str
    ) -> dict[str, tuple[str | None, float, list[str]]]:
        """Return LLM label fallback classifications for a job keyed by file_id."""

    def set_llm_label_override(
        self, job_id: str, file_id: str, label_name: str, updated_at_iso: str
    ) -> None:
        """Persist an LLM label override for a job file."""

    def clear_llm_label_override(self, job_id: str, file_id: str) -> None:
        """Clear an LLM label override for a job file."""

    def get_llm_label_override(self, job_id: str, file_id: str) -> str | None:
        """Return an LLM label override for a job file."""

    def list_llm_label_overrides(self, job_id: str) -> dict[str, str]:
        """Return LLM label overrides for a job keyed by file_id."""

    def save_extraction(
        self,
        job_id: str,
        file_id: str,
        schema_json: str,
        fields_json: str,
        confidences_json: str,
        updated_at: str,
    ) -> None:
        """Persist extraction output for a job file."""

    def get_extraction(self, job_id: str, file_id: str) -> dict | None:
        """Return extraction output for a job file."""

    def get_file_label_override_id(self, job_id: str, file_id: str) -> str | None:
        """Return the override label_id for a job file, if any."""

    def get_file_label_assignment_summary(
        self, job_id: str, file_id: str
    ) -> tuple[str | None, float, str] | None:
        """Return (label_id, score, status) for a job file."""

    def update_label_extraction_schema(
        self, label_id: str, extraction_schema_json: str
    ) -> None:
        """Update extraction schema JSON for a label."""
