from __future__ import annotations

from typing import Protocol

from app.domain.models import FileRef, Job, UndoLog


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
