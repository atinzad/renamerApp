from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.label_fallback import LabelFallbackCandidate, LabelFallbackClassification


@runtime_checkable
class LLMPort(Protocol):
    def classify_label(
        self, ocr_text: str, candidates: list[LabelFallbackCandidate]
    ) -> LabelFallbackClassification:
        """Classify a label name from OCR text."""

    def extract_fields(
        self, schema: dict, ocr_text: str, instructions: str | None = None
    ) -> dict:
        """Extract structured fields from OCR text using the provided schema."""

    def extract_fields_from_image(
        self,
        schema: dict,
        file_bytes: bytes,
        mime_type: str,
        instructions: str | None = None,
    ) -> dict:
        """Extract structured fields from image/PDF bytes using the provided schema."""
