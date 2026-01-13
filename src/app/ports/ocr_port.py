from __future__ import annotations

from typing import Protocol

from app.domain.models import OCRResult


class OCRPort(Protocol):
    def extract_text(self, image_bytes: bytes) -> OCRResult:
        """Extract text from image bytes."""
