from __future__ import annotations

import io
import re

from app.domain.models import OCRResult
from app.ports.ocr_port import OCRPort
from app.services.ocr_merge import merge_ocr_text
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
                pdf_text = self._extract_pdf_text(image_bytes)
                if self._looks_like_text(pdf_text):
                    return OCRResult(text=pdf_text, confidence=None)
                images = self._pdf_to_images(image_bytes)
                if not images:
                    return OCRResult(text="", confidence=None)
                raw_texts = []
                raw_confidences = []
                processed_texts = []
                processed_confidences = []
                for image in images:
                    raw_image = self._auto_rotate(image, pytesseract)
                    raw_texts.append(
                        pytesseract.image_to_string(
                            raw_image,
                            lang=self._language,
                            config="--oem 1 --psm 6",
                        )
                    )
                    raw_confidences.append(self._mean_confidence(pytesseract, raw_image))

                    processed_image = self._preprocess_image(image)
                    processed_image = self._auto_rotate(processed_image, pytesseract)
                    processed_texts.append(
                        pytesseract.image_to_string(
                            processed_image,
                            lang=self._language,
                            config="--oem 1 --psm 6",
                        )
                    )
                    processed_confidences.append(
                        self._mean_confidence(pytesseract, processed_image)
                    )
                raw_text = "\n\n".join(raw_texts)
                processed_text = "\n\n".join(processed_texts)
                merged_text = merge_ocr_text(raw_text, processed_text)
                raw_conf = self._mean_confidence_values(raw_confidences)
                processed_conf = self._mean_confidence_values(processed_confidences)
                confidence = self._max_confidence(raw_conf, processed_conf)
                return OCRResult(text=merged_text, confidence=confidence)
            image = Image.open(io.BytesIO(image_bytes))
        except Exception as exc:
            raise RuntimeError("Failed to load image bytes for OCR.") from exc

        try:
            raw_image = self._auto_rotate(image, pytesseract)
            raw_text = pytesseract.image_to_string(
                raw_image,
                lang=self._language,
                config="--oem 1 --psm 6",
            )
            raw_conf = self._mean_confidence(pytesseract, raw_image)

            processed_image = self._preprocess_image(image)
            processed_image = self._auto_rotate(processed_image, pytesseract)
            processed_text = pytesseract.image_to_string(
                processed_image,
                lang=self._language,
                config="--oem 1 --psm 6",
            )
            processed_conf = self._mean_confidence(pytesseract, processed_image)
            merged_text = merge_ocr_text(raw_text, processed_text)
            confidence = self._max_confidence(raw_conf, processed_conf)
            return OCRResult(text=merged_text, confidence=confidence)
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

    def _max_confidence(self, *values: float | None) -> float | None:
        candidates = [value for value in values if value is not None]
        if not candidates:
            return None
        return max(candidates)

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
            return convert_from_bytes(pdf_bytes, dpi=300)
        except Exception as exc:
            raise RuntimeError("Failed to convert PDF bytes to images.") from exc

    def _extract_pdf_text(self, pdf_bytes: bytes) -> str:
        try:
            from pdfminer.high_level import extract_text
        except ImportError:
            return ""
        try:
            return extract_text(io.BytesIO(pdf_bytes)) or ""
        except Exception:
            return ""

    def _looks_like_text(self, text: str) -> bool:
        if not text:
            return False
        stripped = text.strip()
        if len(stripped) < 20:
            return False
        meaningful = sum(
            ch.isalnum() or ("\u0600" <= ch <= "\u06FF") for ch in stripped
        )
        return meaningful >= 10

    def _auto_rotate(self, image: object, pytesseract: object) -> object:
        try:
            osd = pytesseract.image_to_osd(image, lang=self._language)
        except Exception:
            return image
        match = re.search(r"Rotate:\s*(\d+)", osd)
        if not match:
            return image
        rotate = int(match.group(1))
        if rotate == 0:
            return image
        return image.rotate(-rotate, expand=True)

    def _preprocess_image(self, image: object) -> object:
        from PIL import Image, ImageFilter, ImageOps

        img = image.convert("L")
        img = ImageOps.autocontrast(img)
        img = img.filter(ImageFilter.MedianFilter(size=3))
        img = img.filter(ImageFilter.SHARPEN)
        if max(img.size) < 1200:
            img = img.resize(
                (img.size[0] * 2, img.size[1] * 2),
                resample=Image.BICUBIC,
            )
        return img
