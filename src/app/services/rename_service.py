from __future__ import annotations

from datetime import datetime, timezone

from app.domain.models import RenameOp, UndoLog
from app.domain.rename_logic import (
    build_manual_plan,
    resolve_collisions,
    sanitize_filename,
)
from app.ports.drive_port import DrivePort
from app.ports.storage_port import StoragePort


class RenameService:
    def __init__(self, drive: DrivePort, storage: StoragePort) -> None:
        self._drive = drive
        self._storage = storage

    def preview_manual_rename(self, job_id: str, edits: dict[str, str]) -> list[RenameOp]:
        job = self._storage.get_job(job_id)
        if job is None:
            raise RuntimeError(f"Job not found: {job_id}")

        files = self._storage.get_job_files(job_id)
        ops = build_manual_plan(files, edits)
        sanitized_ops = [
            RenameOp(file_id=op.file_id, old_name=op.old_name, new_name=sanitize_filename(op.new_name))
            for op in ops
        ]

        rename_ids = {op.file_id for op in sanitized_ops}
        existing_names = {file_ref.name for file_ref in files if file_ref.file_id not in rename_ids}
        return resolve_collisions(sanitized_ops, existing_names)

    def apply_rename(self, job_id: str, ops: list[RenameOp]) -> None:
        job = self._storage.get_job(job_id)
        if job is None:
            raise RuntimeError(f"Job not found: {job_id}")

        applied_at = datetime.now(timezone.utc)
        undo = UndoLog(job_id=job_id, created_at=applied_at, ops=ops)
        self._storage.save_undo_log(undo)

        for op in ops:
            self._drive.rename_file(op.file_id, op.new_name)

        self._storage.save_applied_renames(job_id, ops, applied_at.isoformat())

    def undo_last(self, job_id: str) -> None:
        job = self._storage.get_job(job_id)
        if job is None:
            raise RuntimeError(f"Job not found: {job_id}")

        undo = self._storage.get_last_undo_log(job_id)
        if undo is None:
            raise RuntimeError(f"No undo log found for job: {job_id}")

        for op in reversed(undo.ops):
            self._drive.rename_file(op.file_id, op.old_name)

        self._storage.clear_last_undo_log(job_id)
        self._storage.clear_applied_renames(job_id)
