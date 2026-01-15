from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum


class DocType(str, Enum):
    """Supported document types for LLM classification fallback."""

    CIVIL_ID = "CIVIL_ID"
    CONTRACT = "CONTRACT"
    INVOICE = "INVOICE"
    OTHER = "OTHER"


@dataclass
class DocTypeClassification:
    """Doc type classification result with confidence and signals."""

    doc_type: DocType
    confidence: float
    signals: list[str]


def parse_doc_type(value: str) -> DocType:
    """Parse a doc type string into a DocType enum (case-insensitive)."""

    normalized = value.strip().upper()
    for doc_type in DocType:
        if doc_type.value == normalized:
            return doc_type
    raise ValueError(f"Unsupported doc type: {value}")


def clamp_confidence(confidence: float) -> float:
    """Clamp a confidence value to the 0..1 range."""

    if confidence < 0.0:
        return 0.0
    if confidence > 1.0:
        return 1.0
    return confidence


def signals_to_json(signals: list[str]) -> list[str]:
    """Return signals as a JSON-safe list of strings."""

    return [str(signal) for signal in signals]


def signals_from_json(value: list[str] | str | None) -> list[str]:
    """Parse signals from a JSON-safe list or JSON string."""

    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            data = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Signals JSON is invalid") from exc
        if isinstance(data, list):
            return [str(item) for item in data]
    raise ValueError("Signals must be a list or JSON list string")
