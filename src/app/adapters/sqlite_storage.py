from __future__ import annotations

import sqlite3
from datetime import datetime
from uuid import uuid4

from app.domain.models import FileRef, Job, OCRResult, RenameOp, UndoLog
from app.ports.storage_port import StoragePort


class SQLiteStorage(StoragePort):
    def __init__(self, sqlite_path: str) -> None:
        self._sqlite_path = sqlite_path
        self._ensure_schema()

    def create_job(self, folder_id: str) -> Job:
        job = Job(
            job_id=str(uuid4()),
            folder_id=folder_id,
            created_at=datetime.utcnow(),
            status="CREATED",
        )
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO jobs(job_id, folder_id, created_at, status)
                    VALUES (?, ?, ?, ?)
                    """,
                    (job.job_id, job.folder_id, job.created_at.isoformat(), job.status),
                )
            return job
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to create job") from exc

    def get_job(self, job_id: str) -> Job | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT job_id, folder_id, created_at, status, report_file_id
                    FROM jobs
                    WHERE job_id = ?
                    """,
                    (job_id,),
                ).fetchone()
            if row is None:
                return None
            return Job(
                job_id=row[0],
                folder_id=row[1],
                created_at=datetime.fromisoformat(row[2]),
                status=row[3],
                report_file_id=row[4],
            )
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to fetch job") from exc

    def save_job_files(self, job_id: str, files: list[FileRef]) -> None:
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM job_files WHERE job_id = ?", (job_id,))
                conn.executemany(
                    """
                    INSERT INTO job_files(job_id, file_id, name, mime_type, sort_index)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            job_id,
                            file_ref.file_id,
                            file_ref.name,
                            file_ref.mime_type,
                            file_ref.sort_index if file_ref.sort_index is not None else index,
                        )
                        for index, file_ref in enumerate(files)
                    ],
                )
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to save job files") from exc

    def get_job_files(self, job_id: str) -> list[FileRef]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT file_id, name, mime_type, sort_index
                    FROM job_files
                    WHERE job_id = ?
                    ORDER BY sort_index ASC
                    """,
                    (job_id,),
                ).fetchall()
            return [
                FileRef(file_id=row[0], name=row[1], mime_type=row[2], sort_index=row[3])
                for row in rows
            ]
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to fetch job files") from exc

    def save_undo_log(self, undo: UndoLog) -> None:
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM undo_ops WHERE job_id = ?", (undo.job_id,))
                conn.execute("DELETE FROM undo_logs WHERE job_id = ?", (undo.job_id,))
                conn.execute(
                    """
                    INSERT INTO undo_logs(job_id, created_at)
                    VALUES (?, ?)
                    """,
                    (undo.job_id, undo.created_at.isoformat()),
                )
                conn.executemany(
                    """
                    INSERT INTO undo_ops(job_id, file_id, old_name, new_name, op_index)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            undo.job_id,
                            op.file_id,
                            op.old_name,
                            op.new_name,
                            index,
                        )
                        for index, op in enumerate(undo.ops)
                    ],
                )
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to save undo log") from exc

    def get_last_undo_log(self, job_id: str) -> UndoLog | None:
        try:
            with self._connect() as conn:
                log_row = conn.execute(
                    """
                    SELECT job_id, created_at
                    FROM undo_logs
                    WHERE job_id = ?
                    """,
                    (job_id,),
                ).fetchone()
                if log_row is None:
                    return None
                ops_rows = conn.execute(
                    """
                    SELECT file_id, old_name, new_name
                    FROM undo_ops
                    WHERE job_id = ?
                    ORDER BY op_index ASC
                    """,
                    (job_id,),
                ).fetchall()
            ops = [
                RenameOp(file_id=row[0], old_name=row[1], new_name=row[2]) for row in ops_rows
            ]
            return UndoLog(
                job_id=log_row[0],
                created_at=datetime.fromisoformat(log_row[1]),
                ops=ops,
            )
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to fetch undo log") from exc

    def clear_last_undo_log(self, job_id: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM undo_ops WHERE job_id = ?", (job_id,))
                conn.execute("DELETE FROM undo_logs WHERE job_id = ?", (job_id,))
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to clear undo log") from exc

    def set_job_report_file_id(self, job_id: str, report_file_id: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE jobs
                    SET report_file_id = ?
                    WHERE job_id = ?
                    """,
                    (report_file_id, job_id),
                )
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to update report file id") from exc

    def get_job_report_file_id(self, job_id: str) -> str | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT report_file_id
                    FROM jobs
                    WHERE job_id = ?
                    """,
                    (job_id,),
                ).fetchone()
            if row is None:
                return None
            return row[0]
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to fetch report file id") from exc

    def save_ocr_result(self, job_id: str, file_id: str, result: OCRResult) -> None:
        try:
            updated_at = datetime.now().isoformat()
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO ocr_results(job_id, file_id, ocr_text, ocr_confidence, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(job_id, file_id)
                    DO UPDATE SET
                        ocr_text = excluded.ocr_text,
                        ocr_confidence = excluded.ocr_confidence,
                        updated_at = excluded.updated_at
                    """,
                    (
                        job_id,
                        file_id,
                        result.text,
                        result.confidence,
                        updated_at,
                    ),
                )
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to save OCR result") from exc

    def get_ocr_result(self, job_id: str, file_id: str) -> OCRResult | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT ocr_text, ocr_confidence
                    FROM ocr_results
                    WHERE job_id = ? AND file_id = ?
                    """,
                    (job_id, file_id),
                ).fetchone()
            if row is None:
                return None
            return OCRResult(text=row[0], confidence=row[1])
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to fetch OCR result") from exc

    def _ensure_schema(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs(
                        job_id TEXT PRIMARY KEY,
                        folder_id TEXT,
                        created_at TEXT,
                        status TEXT,
                        report_file_id TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS job_files(
                        job_id TEXT,
                        file_id TEXT,
                        name TEXT,
                        mime_type TEXT,
                        sort_index INTEGER
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS undo_logs(
                        job_id TEXT PRIMARY KEY,
                        created_at TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS undo_ops(
                        job_id TEXT,
                        file_id TEXT,
                        old_name TEXT,
                        new_name TEXT,
                        op_index INTEGER
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ocr_results(
                        job_id TEXT,
                        file_id TEXT,
                        ocr_text TEXT,
                        ocr_confidence REAL,
                        updated_at TEXT,
                        PRIMARY KEY(job_id, file_id)
                    )
                    """
                )
                columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
                }
                if "report_file_id" not in columns:
                    conn.execute("ALTER TABLE jobs ADD COLUMN report_file_id TEXT")
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to initialize storage schema") from exc

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._sqlite_path)
