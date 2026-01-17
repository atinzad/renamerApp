from __future__ import annotations

from dataclasses import dataclass

GENERIC_MIN_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "document_language": {"type": "string"},
        "notes": {"type": "string"},
    },
}


@dataclass
class ExtractedFields:
    fields: dict[str, object]
    confidences: dict[str, float | None]
    needs_review: bool
    warnings: list[str]
