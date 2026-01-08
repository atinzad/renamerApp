from dataclasses import dataclass
from datetime import datetime


@dataclass
class FileRef:
    file_id: str
    name: str
    mime_type: str


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
