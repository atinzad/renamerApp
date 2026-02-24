from dataclasses import dataclass
from datetime import datetime


@dataclass
class FileRef:
    file_id: str
    name: str
    mime_type: str
    sort_index: int | None = None


@dataclass
class FolderRef:
    folder_id: str
    name: str


@dataclass
class Job:
    job_id: str
    folder_id: str
    created_at: datetime
    status: str
    report_file_id: str | None = None


@dataclass
class RenameOp:
    file_id: str
    old_name: str
    new_name: str


@dataclass
class UndoLog:
    job_id: str
    created_at: datetime
    ops: list[RenameOp]


@dataclass
class OCRResult:
    text: str
    confidence: float | None


@dataclass
class JobFileRecord:
    job_id: str
    file_id: str
    name: str
    mime_type: str
    sort_index: int | None = None


@dataclass
class LabelAssignment:
    job_id: str
    file_id: str
    label_id: str | None
    status: str
    score: float
    updated_at: str | None = None


@dataclass
class FileLabelOverride:
    job_id: str
    file_id: str
    label_id: str | None
    updated_at: str | None = None


@dataclass
class LLMLabelClassification:
    job_id: str
    file_id: str
    label_name: str | None
    confidence: float
    signals: list[str]
    updated_at: str | None = None


@dataclass
class ExtractionRecord:
    job_id: str
    file_id: str
    schema_json: str | None
    fields_json: str | None
    confidences_json: str | None = None
    updated_at: str | None = None


@dataclass
class AppliedRename:
    job_id: str
    file_id: str
    old_name: str
    new_name: str
    applied_at: str


@dataclass
class FileTimingRecord:
    job_id: str
    file_id: str
    ocr_ms: int | None
    classify_ms: int | None
    extract_ms: int | None
    updated_at: str
