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
            if self._is_pdf_bytes(image_bytes):
                images = self._pdf_to_images(image_bytes)
                if not images:
                    return OCRResult(text="", confidence=None)
                texts = []
                confidences = []
                for image in images:
                    texts.append(pytesseract.image_to_string(image, lang=self._language))
                    confidences.append(self._mean_confidence(pytesseract, image))
                text = "\n\n".join(texts)
                confidence = self._mean_confidence_values(confidences)
                return OCRResult(text=text, confidence=confidence)
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

    def _mean_confidence_values(self, values: list[float | None]) -> float | None:
        filtered = [value for value in values if value is not None]
        if not filtered:
            return None
        return sum(filtered) / len(filtered)

    def _is_pdf_bytes(self, image_bytes: bytes) -> bool:
        return image_bytes.lstrip().startswith(b"%PDF")

    def _pdf_to_images(self, pdf_bytes: bytes) -> list[object]:
        try:
            from pdf2image import convert_from_bytes
        except ImportError as exc:
            raise RuntimeError(
                "pdf2image is required to OCR PDF files. Install with: pip install pdf2image. "
                "Poppler is also required on your system."
            ) from exc
        try:
            return convert_from_bytes(pdf_bytes)
        except Exception as exc:
            raise RuntimeError("Failed to convert PDF bytes to images.") from exc
