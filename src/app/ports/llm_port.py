from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.label_fallback import LabelFallbackCandidate, LabelFallbackClassification


@runtime_checkable
class LLMPort(Protocol):
    def classify_label(
        self, ocr_text: str, candidates: list[LabelFallbackCandidate]
    ) -> LabelFallbackClassification:
        """Classify a label name from OCR text."""

    def extract_fields(self, schema: dict, ocr_text: str) -> dict:
        """Extract structured fields from OCR text using the provided schema."""
