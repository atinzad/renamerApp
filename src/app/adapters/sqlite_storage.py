from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from uuid import uuid4

from app.domain.labels import Label, LabelExample
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

    def create_label(
        self, name: str, extraction_schema_json: str, naming_template: str
    ) -> Label:
        label = Label(
            label_id=str(uuid4()),
            name=name,
            is_active=True,
            created_at=datetime.utcnow(),
            extraction_schema_json=extraction_schema_json,
            naming_template=naming_template,
        )
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO labels(
                        label_id, name, is_active, created_at, extraction_schema_json, naming_template
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        label.label_id,
                        label.name,
                        1,
                        label.created_at.isoformat(),
                        label.extraction_schema_json,
                        label.naming_template,
                    ),
                )
            return label
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to create label") from exc

    def deactivate_label(self, label_id: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE labels
                    SET is_active = 0
                    WHERE label_id = ?
                    """,
                    (label_id,),
                )
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to deactivate label") from exc

    def list_labels(self, include_inactive: bool = False) -> list[Label]:
        try:
            with self._connect() as conn:
                if include_inactive:
                    rows = conn.execute(
                        """
                        SELECT label_id, name, is_active, created_at, extraction_schema_json, naming_template
                        FROM labels
                        ORDER BY created_at ASC, label_id ASC
                        """
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT label_id, name, is_active, created_at, extraction_schema_json, naming_template
                        FROM labels
                        WHERE is_active = 1
                        ORDER BY created_at ASC, label_id ASC
                        """
                    ).fetchall()
            return [
                Label(
                    label_id=row[0],
                    name=row[1],
                    is_active=bool(row[2]),
                    created_at=datetime.fromisoformat(row[3]),
                    extraction_schema_json=row[4],
                    naming_template=row[5],
                )
                for row in rows
            ]
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to list labels") from exc

    def get_label(self, label_id: str) -> Label | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT label_id, name, is_active, created_at, extraction_schema_json, naming_template
                    FROM labels
                    WHERE label_id = ?
                    """,
                    (label_id,),
                ).fetchone()
            if row is None:
                return None
            return Label(
                label_id=row[0],
                name=row[1],
                is_active=bool(row[2]),
                created_at=datetime.fromisoformat(row[3]),
                extraction_schema_json=row[4],
                naming_template=row[5],
            )
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to fetch label") from exc

    def count_labels(self) -> int:
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) FROM labels").fetchone()
            return int(row[0] if row else 0)
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to count labels") from exc

    def attach_label_example(self, label_id: str, file_id: str, filename: str) -> LabelExample:
        example = LabelExample(
            example_id=str(uuid4()),
            label_id=label_id,
            file_id=file_id,
            filename=filename,
            created_at=datetime.utcnow(),
        )
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO label_examples(example_id, label_id, file_id, filename, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        example.example_id,
                        example.label_id,
                        example.file_id,
                        example.filename,
                        example.created_at.isoformat(),
                    ),
                )
            return example
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to attach label example") from exc

    def list_label_examples(self, label_id: str) -> list[LabelExample]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT example_id, label_id, file_id, filename, created_at
                    FROM label_examples
                    WHERE label_id = ?
                    ORDER BY created_at ASC, example_id ASC
                    """,
                    (label_id,),
                ).fetchall()
            return [
                LabelExample(
                    example_id=row[0],
                    label_id=row[1],
                    file_id=row[2],
                    filename=row[3],
                    created_at=datetime.fromisoformat(row[4]),
                )
                for row in rows
            ]
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to list label examples") from exc

    def save_label_example_features(
        self,
        example_id: str,
        ocr_text: str,
        embedding: list[float] | None,
        token_fingerprint: set[str] | None,
    ) -> None:
        try:
            updated_at = datetime.utcnow().isoformat()
            embedding_json = json.dumps(embedding) if embedding is not None else None
            token_json = (
                json.dumps(sorted(token_fingerprint))
                if token_fingerprint is not None
                else None
            )
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO label_example_features(
                        example_id, ocr_text, embedding_json, token_fingerprint, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(example_id)
                    DO UPDATE SET
                        ocr_text = excluded.ocr_text,
                        embedding_json = excluded.embedding_json,
                        token_fingerprint = excluded.token_fingerprint,
                        updated_at = excluded.updated_at
                    """,
                    (example_id, ocr_text, embedding_json, token_json, updated_at),
                )
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to save label example features") from exc

    def get_label_example_features(self, example_id: str) -> dict | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT ocr_text, embedding_json, token_fingerprint
                    FROM label_example_features
                    WHERE example_id = ?
                    """,
                    (example_id,),
                ).fetchone()
            if row is None:
                return None
            embedding = json.loads(row[1]) if row[1] else None
            tokens = set(json.loads(row[2])) if row[2] else None
            return {"ocr_text": row[0], "embedding": embedding, "token_fingerprint": tokens}
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise RuntimeError("Failed to fetch label example features") from exc

    def upsert_file_label_assignment(
        self,
        job_id: str,
        file_id: str,
        label_id: str | None,
        score: float,
        status: str,
    ) -> None:
        try:
            updated_at = datetime.utcnow().isoformat()
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO file_label_assignments(
                        job_id, file_id, label_id, score, status, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id, file_id)
                    DO UPDATE SET
                        label_id = excluded.label_id,
                        score = excluded.score,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    (job_id, file_id, label_id, score, status, updated_at),
                )
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to upsert label assignment") from exc

    def get_file_label_assignment(self, job_id: str, file_id: str) -> dict | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT job_id, file_id, label_id, score, status, updated_at
                    FROM file_label_assignments
                    WHERE job_id = ? AND file_id = ?
                    """,
                    (job_id, file_id),
                ).fetchone()
            if row is None:
                return None
            return {
                "job_id": row[0],
                "file_id": row[1],
                "label_id": row[2],
                "score": row[3],
                "status": row[4],
                "updated_at": row[5],
            }
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to fetch label assignment") from exc

    def list_file_label_assignments(self, job_id: str) -> list[dict]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT job_id, file_id, label_id, score, status, updated_at
                    FROM file_label_assignments
                    WHERE job_id = ?
                    ORDER BY file_id ASC
                    """,
                    (job_id,),
                ).fetchall()
            return [
                {
                    "job_id": row[0],
                    "file_id": row[1],
                    "label_id": row[2],
                    "score": row[3],
                    "status": row[4],
                    "updated_at": row[5],
                }
                for row in rows
            ]
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to list label assignments") from exc

    def upsert_file_label_override(
        self, job_id: str, file_id: str, label_id: str | None
    ) -> None:
        try:
            updated_at = datetime.utcnow().isoformat()
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO file_label_overrides(job_id, file_id, label_id, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(job_id, file_id)
                    DO UPDATE SET
                        label_id = excluded.label_id,
                        updated_at = excluded.updated_at
                    """,
                    (job_id, file_id, label_id, updated_at),
                )
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to upsert label override") from exc

    def get_file_label_override(self, job_id: str, file_id: str) -> dict | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT job_id, file_id, label_id, updated_at
                    FROM file_label_overrides
                    WHERE job_id = ? AND file_id = ?
                    """,
                    (job_id, file_id),
                ).fetchone()
            if row is None:
                return None
            return {
                "job_id": row[0],
                "file_id": row[1],
                "label_id": row[2],
                "updated_at": row[3],
            }
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to fetch label override") from exc

    def list_file_label_overrides(self, job_id: str) -> list[dict]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT job_id, file_id, label_id, updated_at
                    FROM file_label_overrides
                    WHERE job_id = ?
                    ORDER BY file_id ASC
                    """,
                    (job_id,),
                ).fetchall()
            return [
                {
                    "job_id": row[0],
                    "file_id": row[1],
                    "label_id": row[2],
                    "updated_at": row[3],
                }
                for row in rows
            ]
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to list label overrides") from exc

    def bulk_insert_label_presets(self, labels: list[dict]) -> None:
        try:
            with self._connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO labels(
                        label_id, name, is_active, created_at, extraction_schema_json, naming_template
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            label.get("label_id", str(uuid4())),
                            label.get("name", ""),
                            1 if label.get("is_active", True) else 0,
                            label.get("created_at", datetime.utcnow().isoformat()),
                            label.get("extraction_schema_json", "{}"),
                            label.get("naming_template", ""),
                        )
                        for label in labels
                    ],
                )
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to insert label presets") from exc

    def export_labels_for_presets(self) -> list[dict]:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT label_id, name, is_active, created_at, extraction_schema_json, naming_template
                    FROM labels
                    ORDER BY created_at ASC, label_id ASC
                    """
                ).fetchall()
            return [
                {
                    "label_id": row[0],
                    "name": row[1],
                    "is_active": bool(row[2]),
                    "created_at": row[3],
                    "extraction_schema_json": row[4],
                    "naming_template": row[5],
                }
                for row in rows
            ]
        except sqlite3.Error as exc:
            raise RuntimeError("Failed to export labels") from exc

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
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS labels(
                        label_id TEXT PRIMARY KEY,
                        name TEXT,
                        is_active INTEGER,
                        created_at TEXT,
                        extraction_schema_json TEXT,
                        naming_template TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS label_examples(
                        example_id TEXT PRIMARY KEY,
                        label_id TEXT,
                        file_id TEXT,
                        filename TEXT,
                        created_at TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS label_example_features(
                        example_id TEXT PRIMARY KEY,
                        ocr_text TEXT,
                        embedding_json TEXT,
                        token_fingerprint TEXT,
                        updated_at TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS file_label_assignments(
                        job_id TEXT,
                        file_id TEXT,
                        label_id TEXT,
                        score REAL,
                        status TEXT,
                        updated_at TEXT,
                        PRIMARY KEY(job_id, file_id)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS file_label_overrides(
                        job_id TEXT,
                        file_id TEXT,
                        label_id TEXT,
                        updated_at TEXT,
                        PRIMARY KEY(job_id, file_id)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_label_examples_label_id
                    ON label_examples(label_id)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_assignments_job_id
                    ON file_label_assignments(job_id)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_overrides_job_id
                    ON file_label_overrides(job_id)
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
