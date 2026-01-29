from __future__ import annotations

import argparse
import io
import os
from pathlib import Path

from app.services.ocr_merge import merge_ocr_text

def _extract_pdf_text_layer(pdf_bytes: bytes) -> str:
    try:
        from pdfminer.high_level import extract_text
    except ImportError:
        return ""
    try:
        return extract_text(io.BytesIO(pdf_bytes)) or ""
    except Exception:
        return ""


def _ocr_pdf_raw(pdf_bytes: bytes, language: str) -> tuple[str, float | None]:
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except ImportError as exc:
        raise RuntimeError(
            "pytesseract and pdf2image are required for OCR. "
            "Install with: pip install pytesseract pdf2image pillow"
        ) from exc

    images = convert_from_bytes(pdf_bytes, dpi=300)
    texts: list[str] = []
    confidences: list[float] = []
    for image in images:
        text = pytesseract.image_to_string(
            image,
            lang=language,
            config="--oem 1 --psm 6",
        )
        texts.append(text)
        data = pytesseract.image_to_data(
            image,
            lang=language,
            output_type=pytesseract.Output.DICT,
        )
        for value in data.get("conf", []):
            if value in (-1, "-1", None, ""):
                continue
            try:
                confidences.append(float(value))
            except (TypeError, ValueError):
                continue
    ocr_text = "\n\n".join(texts)
    mean_conf = sum(confidences) / len(confidences) if confidences else None
    return ocr_text, mean_conf


def _ocr_pdf_processed(pdf_bytes: bytes, language: str) -> tuple[str, float | None]:
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except ImportError as exc:
        raise RuntimeError(
            "pytesseract and pdf2image are required for OCR. "
            "Install with: pip install pytesseract pdf2image pillow"
        ) from exc
    from PIL import Image, ImageFilter, ImageOps

    images = convert_from_bytes(pdf_bytes, dpi=300)
    texts: list[str] = []
    confidences: list[float] = []
    for image in images:
        img = image.convert("L")
        img = ImageOps.autocontrast(img)
        img = img.filter(ImageFilter.MedianFilter(size=3))
        img = img.filter(ImageFilter.SHARPEN)
        if max(img.size) < 1200:
            img = img.resize(
                (img.size[0] * 2, img.size[1] * 2),
                resample=Image.BICUBIC,
            )
        text = pytesseract.image_to_string(
            img,
            lang=language,
            config="--oem 1 --psm 6",
        )
        texts.append(text)
        data = pytesseract.image_to_data(
            img,
            lang=language,
            output_type=pytesseract.Output.DICT,
        )
        for value in data.get("conf", []):
            if value in (-1, "-1", None, ""):
                continue
            try:
                confidences.append(float(value))
            except (TypeError, ValueError):
                continue
    ocr_text = "\n\n".join(texts)
    mean_conf = sum(confidences) / len(confidences) if confidences else None
    return ocr_text, mean_conf


def _snippet(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    return cleaned[:limit]


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare PDF text layer vs OCR output.")
    parser.add_argument("pdf", help="Path to a PDF file.")
    parser.add_argument("--snippet", type=int, default=400, help="Snippet length to print.")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        raise SystemExit(f"File not found: {pdf_path}")
    pdf_bytes = pdf_path.read_bytes()

    language = os.getenv("OCR_LANG", "ara+eng")

    text_layer = _extract_pdf_text_layer(pdf_bytes)
    raw_text, raw_conf = _ocr_pdf_raw(pdf_bytes, language)
    processed_text, processed_conf = _ocr_pdf_processed(pdf_bytes, language)
    merged_text = merge_ocr_text(raw_text, processed_text)

    print("Text layer")
    print(f"  chars: {len(text_layer)}")
    print(f"  snippet: {_snippet(text_layer, args.snippet)}")
    print("")
    print("OCR (raw)")
    print(f"  chars: {len(raw_text)}")
    print(f"  confidence: {raw_conf if raw_conf is not None else 'None'}")
    print(f"  snippet: {_snippet(raw_text, args.snippet)}")
    print("")
    print("OCR (preprocessed)")
    print(f"  chars: {len(processed_text)}")
    print(f"  confidence: {processed_conf if processed_conf is not None else 'None'}")
    print(f"  snippet: {_snippet(processed_text, args.snippet)}")
    print("")
    print("OCR (merged)")
    print(f"  chars: {len(merged_text)}")
    print("  confidence: n/a")
    print(f"  snippet: {_snippet(merged_text, args.snippet)}")


if __name__ == "__main__":
    main()
