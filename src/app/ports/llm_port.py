from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.doc_types import DocTypeClassification


@runtime_checkable
class LLMPort(Protocol):
    def classify_doc_type(self, ocr_text: str) -> DocTypeClassification:
        """Classify a document type from OCR text."""
