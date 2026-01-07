from __future__ import annotations

from typing import Any, Protocol

_PENDING_TOKEN = "<<<PENDING_EXTRACTION>>>"


class FileRefLike(Protocol):
    file_id: str
    name: str
    mime_type: str
    sort_index: int


def _get_value(item: Any, key: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def render_increment2_report(
    *,
    job_id: str,
    folder_id: str,
    generated_at_local_iso: str,
    files: list[dict] | list[FileRefLike],
) -> str:
    ordered_files = sorted(
        files,
        key=lambda item: (
            _get_value(item, "sort_index", 0),
            _get_value(item, "name", ""),
            _get_value(item, "file_id", ""),
        ),
    )
    lines: list[str] = [
        "REPORT_VERSION: 1",
        f"JOB_ID: {job_id}",
        f"FOLDER_ID: {folder_id}",
        f"GENERATED_AT: {generated_at_local_iso}",
    ]
    for index, item in enumerate(ordered_files, start=1):
        lines.extend(
            [
                "--- FILE START ---",
                f"INDEX: {index}",
                f"FILE_NAME: {_get_value(item, 'name', '')}",
                f"FILE_ID: {_get_value(item, 'file_id', '')}",
                f"MIME_TYPE: {_get_value(item, 'mime_type', '')}",
                "",
                "EXTRACTED_TEXT:",
                _PENDING_TOKEN,
                "",
                "EXTRACTED_FIELDS_JSON:",
                _PENDING_TOKEN,
                "--- FILE END ---",
            ]
        )
    return "\n".join(lines) + "\n"
