from __future__ import annotations

import io

from app.domain.models import OCRResult
from app.ports.ocr_port import OCRPort
from app.settings import OCR_LANG


class TesseractOCRAdapter(OCRPort):
    def __init__(self, language: str | None = None) -> None:
        self._language = language or OCR_LANG

    def extract_text(self, image_bytes: bytes) -> OCRResult:
        try:
            import pytesseract
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError(
                "pytesseract and Pillow are required for OCR. "
                "Install with: pip install pytesseract pillow"
            ) from exc

        try:
            image = Image.open(io.BytesIO(image_bytes))
        except Exception as exc:
            raise RuntimeError("Failed to load image bytes for OCR.") from exc

        try:
            text = pytesseract.image_to_string(image, lang=self._language)
            confidence = self._mean_confidence(pytesseract, image)
            return OCRResult(text=text, confidence=confidence)
        except pytesseract.TesseractNotFoundError as exc:
            raise RuntimeError(
                "Tesseract OCR engine not found. Install tesseract-ocr and ensure it is on PATH."
            ) from exc
        except Exception as exc:
            raise RuntimeError("Failed to run OCR on image bytes.") from exc

    def _mean_confidence(self, pytesseract: object, image: object) -> float | None:
        data = pytesseract.image_to_data(
            image,
            lang=self._language,
            output_type=pytesseract.Output.DICT,
        )
        conf_values: list[float] = []
        for value in data.get("conf", []):
            if value in (-1, "-1", None, ""):
                continue
            try:
                conf_values.append(float(value))
            except (TypeError, ValueError):
                continue
        if not conf_values:
            return None
        return sum(conf_values) / len(conf_values)
