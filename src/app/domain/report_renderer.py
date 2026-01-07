from __future__ import annotations

from typing import Any, Iterable, Protocol

_PENDING_TOKEN = "<<<PENDING_EXTRACTION>>>"


class JobRow(Protocol):
    job_id: str
    folder_id: str


class JobFileRow(Protocol):
    sort_index: int
    name: str
    file_id: str
    mime_type: str


def _get_value(row: Any, key: str, default: Any = "") -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def render_report(
    job: JobRow,
    job_files: list[JobFileRow],
    generated_at_local_iso: str,
    local_job_date: str,
) -> str:
    _ = local_job_date  # reserved for future schema fields
    ordered_files = sorted(
        job_files,
        key=lambda row: (
            _get_value(row, "sort_index", 0),
            _get_value(row, "name", ""),
            _get_value(row, "file_id", ""),
        ),
    )
    lines: list[str] = [
        "REPORT_VERSION: 1",
        f"JOB_ID: {job.job_id}",
        f"FOLDER_ID: {job.folder_id}",
        f"GENERATED_AT: {generated_at_local_iso}",
    ]
    for index, file_row in enumerate(ordered_files, start=1):
        lines.extend(
            [
                "--- FILE START ---",
                f"INDEX: {index}",
                f"FILE_NAME: {_get_value(file_row, 'name', '')}",
                f"FILE_ID: {_get_value(file_row, 'file_id', '')}",
                f"MIME_TYPE: {_get_value(file_row, 'mime_type', '')}",
                "",
                "EXTRACTED_TEXT:",
                _PENDING_TOKEN,
                "",
                "EXTRACTED_FIELDS_JSON:",
                _PENDING_TOKEN,
                "--- FILE END ---",
            ]
        )
    return "\n".join(lines)
