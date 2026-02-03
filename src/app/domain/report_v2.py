from __future__ import annotations

from dataclasses import dataclass
from typing import Any

UNKNOWN_TOKEN = "UNKNOWN"
UNLABELED_TOKEN = "UNLABELED"


@dataclass
class FinalReportFileBlock:
    index: int
    final_name: str
    file_id: str
    final_label: str | None
    extracted_fields: dict[str, Any] | None
    schema: dict[str, Any] | None = None


@dataclass
class FinalReportModel:
    job_id: str
    folder_id: str
    generated_at_local_iso: str
    files: list[FinalReportFileBlock]


def pretty_print_fields(fields: dict[str, Any] | None, schema: dict | None) -> list[str]:
    if not isinstance(fields, dict) or not fields:
        return [UNKNOWN_TOKEN]
    ordered_keys = _schema_keys(schema) if isinstance(schema, dict) else sorted(fields.keys())
    lines: list[str] = []
    for key in ordered_keys:
        value = fields.get(key)
        lines.append(f"{key}: {_format_value(value)}")
    return lines


def render_report_v2(model: FinalReportModel) -> str:
    lines: list[str] = [
        "REPORT_VERSION: 2",
        f"JOB_ID: {model.job_id}",
        f"FOLDER_ID: {model.folder_id}",
        f"GENERATED_AT: {model.generated_at_local_iso}",
    ]
    for file_block in model.files:
        label = file_block.final_label or UNLABELED_TOKEN
        field_lines = pretty_print_fields(file_block.extracted_fields, file_block.schema)
        lines.extend(
            [
                "--- FILE START ---",
                f"INDEX: {file_block.index}",
                f"FINAL_NAME: {file_block.final_name}",
                f"FILE_ID: {file_block.file_id}",
                f"FINAL_LABEL: {label}",
                "",
                "EXTRACTED_FIELDS:",
                *field_lines,
                "--- FILE END ---",
            ]
        )
    return "\n".join(lines) + "\n"


def _schema_keys(schema: dict[str, Any]) -> list[str]:
    keys = list(schema.keys())
    return keys if keys else []


def _format_value(value: Any) -> str:
    if value is None:
        return UNKNOWN_TOKEN
    if isinstance(value, str):
        return value.strip() if value.strip() else UNKNOWN_TOKEN
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(items) if items else UNKNOWN_TOKEN
    if isinstance(value, dict):
        parts = []
        for subkey in sorted(value.keys()):
            subval = value.get(subkey)
            parts.append(f"{subkey}={_format_value(subval)}")
        return "; ".join(parts) if parts else UNKNOWN_TOKEN
    return str(value)
