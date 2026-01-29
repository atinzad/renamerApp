from __future__ import annotations

import argparse
import io
import json
import os
import re
import sqlite3
import base64
import time
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

from app.services.ocr_merge import merge_ocr_text
from app.settings import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL


def _is_pdf_bytes(file_bytes: bytes) -> bool:
    return file_bytes.lstrip().startswith(b"%PDF")


def _auto_rotate(image: object, pytesseract: object, language: str) -> object:
    try:
        osd = pytesseract.image_to_osd(image, lang=language)
    except Exception:
        return image
    match = re.search(r"Rotate:\\s*(\\d+)", osd)
    if not match:
        return image
    rotate = int(match.group(1))
    if rotate == 0:
        return image
    return image.rotate(-rotate, expand=True)


def _preprocess_image(image: object) -> object:
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


def _load_images(file_bytes: bytes) -> list[object]:
    if _is_pdf_bytes(file_bytes):
        try:
            from pdf2image import convert_from_bytes
        except ImportError as exc:
            raise RuntimeError(
                "pdf2image is required for OCR. Install with: pip install pdf2image pillow"
            ) from exc
        return convert_from_bytes(file_bytes, dpi=300)
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Pillow is required for OCR. Install with: pip install pillow") from exc
    return [Image.open(io.BytesIO(file_bytes))]


def _ocr_raw_and_preprocessed(file_bytes: bytes, language: str) -> tuple[str, str]:
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError(
            "pytesseract is required for OCR. Install with: pip install pytesseract pillow"
        ) from exc

    images = _load_images(file_bytes)
    raw_texts: list[str] = []
    processed_texts: list[str] = []

    for image in images:
        raw_image = _auto_rotate(image, pytesseract, language)
        raw_texts.append(
            pytesseract.image_to_string(
                raw_image,
                lang=language,
                config="--oem 1 --psm 6",
            )
        )

        processed_image = _preprocess_image(image)
        processed_image = _auto_rotate(processed_image, pytesseract, language)
        processed_texts.append(
            pytesseract.image_to_string(
                processed_image,
                lang=language,
                config="--oem 1 --psm 6",
            )
        )

    return "\n\n".join(raw_texts), "\n\n".join(processed_texts)


def _load_label_schema(db_path: Path, label_name: str) -> tuple[dict, str]:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "SELECT extraction_schema_json, extraction_instructions FROM labels WHERE name=?",
        (label_name,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        raise RuntimeError(f"Label not found: {label_name}")
    schema_json, instructions = row
    return json.loads(schema_json), instructions or ""


def _run_extraction_text(
    ocr_text: str,
    schema: dict,
    instructions: str,
    cache_buster: str | None = None,
) -> tuple[dict, dict]:
    if _looks_like_placeholder_key(OPENAI_API_KEY):
        return {"_error": "OPENAI_API_KEY missing or placeholder"}, {}
    system_prompt = "You are a structured extraction assistant. "
    if instructions.strip():
        system_prompt += instructions.strip() + "\n\n"
    system_prompt += (
        "Return JSON that matches the provided schema. "
        "If a value is missing, return \"UNKNOWN\" for that field."
    )
    if cache_buster:
        system_prompt += f"\n\nCache-buster: {cache_buster}"
    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                    "text": (
                        "Extract fields from the OCR text using this schema.\n"
                        f"Schema:\n{json.dumps(schema)}\n\n"
                        "OCR text:\n"
                        f"{ocr_text}"
                    ),
                    }
                ],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "extracted_fields",
                "schema": schema,
                "strict": True,
            }
        },
    }
    response = _post_openai(payload)
    if "output" not in response:
        return response, _extract_usage(response)
    return _parse_response_json(response), _extract_usage(response)


def _images_from_file_bytes(file_bytes: bytes) -> list[bytes]:
    images = _load_images(file_bytes)
    encoded: list[bytes] = []
    from PIL import Image

    for image in images:
        if image.mode != "RGB":
            image = image.convert("RGB")
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        encoded.append(buf.getvalue())
    return encoded


def _run_extraction_direct_image(
    file_bytes: bytes,
    schema: dict,
    instructions: str,
    cache_buster: str | None = None,
) -> tuple[dict, dict]:
    if _looks_like_placeholder_key(OPENAI_API_KEY):
        return {"_error": "OPENAI_API_KEY missing or placeholder"}, {}

    system_prompt = "You are a structured extraction assistant. "
    if instructions.strip():
        system_prompt += instructions.strip() + "\n\n"
    system_prompt += (
        "Return JSON that matches the provided schema. "
        "If a value is missing, return \"UNKNOWN\" for that field."
    )
    if cache_buster:
        system_prompt += f"\n\nCache-buster: {cache_buster}"

    schema_json = json.dumps(schema)
    content_items = [
        {
            "type": "input_text",
            "text": (
                "Extract fields from the document images using this schema.\n"
                f"Schema:\n{schema_json}"
            ),
        }
    ]

    for image_bytes in _images_from_file_bytes(file_bytes):
        data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        content_items.append({"type": "input_image", "image_url": data_url})

    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": content_items,
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "extracted_fields",
                "schema": schema,
                "strict": True,
            }
        },
    }

    response = _post_openai(payload)
    if "output" not in response:
        return response, _extract_usage(response)
    return _parse_response_json(response), _extract_usage(response)


def _post_openai(payload: dict) -> dict:
    try:
        response = requests.post(
            f"{OPENAI_BASE_URL.rstrip('/')}/responses",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        status = getattr(exc.response, "status_code", None)
        body = getattr(exc.response, "text", "") if getattr(exc, "response", None) else ""
        return {
            "_error": "OPENAI_REQUEST_FAILED",
            "status_code": status,
            "detail": body[:1000],
        }


def _parse_response_json(payload: dict) -> dict:
    output_items = payload.get("output", [])
    for item in output_items:
        content = item.get("content", [])
        for block in content:
            if block.get("type") == "output_json":
                json_payload = block.get("json")
                return json_payload if isinstance(json_payload, dict) else {"_error": "INVALID_JSON"}
            if block.get("type") in {"output_text", "text"}:
                text = block.get("text", "") or ""
                parsed = _parse_json_from_text(text)
                if parsed is not None:
                    return parsed
                return {"_error": "INVALID_JSON", "raw_text": text[:1000]}
    return {"_error": "NO_OUTPUT_TEXT"}


def _parse_json_from_text(text: str) -> dict | None:
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _extract_usage(payload: dict) -> dict:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return {}
    return usage


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    try:
        import tiktoken  # type: ignore
    except Exception:
        return max(1, len(text) // 4)
    try:
        enc = tiktoken.encoding_for_model(OPENAI_MODEL)
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def _estimate_input_tokens_for_text(ocr_text: str, schema: dict, instructions: str) -> int:
    system_prompt = "You are a structured extraction assistant. "
    if instructions.strip():
        system_prompt += instructions.strip() + "\n\n"
    system_prompt += (
        "Return JSON that matches the provided schema. "
        "If a value is missing, return \"UNKNOWN\" for that field."
    )
    user_prompt = (
        "Extract fields from the OCR text using this schema.\n"
        f"Schema:\n{json.dumps(schema)}\n\n"
        "OCR text:\n"
        f"{ocr_text}"
    )
    return _estimate_tokens(system_prompt) + _estimate_tokens(user_prompt)


def _estimate_input_tokens_for_image(schema: dict, instructions: str, image_count: int) -> int:
    system_prompt = "You are a structured extraction assistant. "
    if instructions.strip():
        system_prompt += instructions.strip() + "\n\n"
    system_prompt += (
        "Return JSON that matches the provided schema. "
        "If a value is missing, return \"UNKNOWN\" for that field."
    )
    user_prompt = (
        "Extract fields from the document images using this schema.\n"
        f"Schema:\n{json.dumps(schema)}"
    )
    # Image token cost isn't included here; add a rough heuristic per image.
    text_tokens = _estimate_tokens(system_prompt) + _estimate_tokens(user_prompt)
    image_tokens = image_count * 1000
    return text_tokens + image_tokens


def _looks_like_placeholder_key(value: str) -> bool:
    if not value:
        return True
    lowered = value.strip().lower()
    if lowered in {"...", "your_api_key", "your-openai-api-key"}:
        return True
    if "..." in lowered:
        return True
    return False


def _print_block(title: str, text: str) -> None:
    print(title)
    print(f"  chars: {len(text)}")
    print("")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare LLM extraction results across OCR strategies."
    )
    parser.add_argument("file", help="Path to a PDF or image file.")
    parser.add_argument("--label", default="Civil_ID", help="Label name from app.db.")
    parser.add_argument("--db", default="app.db", help="Path to the sqlite db.")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Add a random cache-buster to avoid server-side cached tokens.",
    )
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        raise SystemExit(f"File not found: {file_path}")

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    file_bytes = file_path.read_bytes()
    language = os.getenv("OCR_LANG", "ara+eng")

    raw_text, processed_text = _ocr_raw_and_preprocessed(file_bytes, language)
    merged_text = merge_ocr_text(raw_text, processed_text)

    schema, instructions = _load_label_schema(db_path, args.label)
    image_count = len(_load_images(file_bytes))
    cache_buster = str(uuid.uuid4()) if args.no_cache else None

    print(f"Label: {args.label}")
    print("")

    _print_block("OCR (raw)", raw_text)
    _print_block("OCR (preprocessed)", processed_text)
    _print_block("OCR (merged)", merged_text)

    print("LLM extraction (raw)")
    start = time.perf_counter()
    raw_result, raw_usage = _run_extraction_text(
        raw_text, schema, instructions, cache_buster
    )
    raw_elapsed = time.perf_counter() - start
    print(f"  elapsed_s: {raw_elapsed:.2f}")
    if raw_usage:
        print(f"  usage: {json.dumps(raw_usage)}")
    print(json.dumps(raw_result, indent=2))
    print("")
    print("LLM extraction (preprocessed)")
    start = time.perf_counter()
    processed_result, processed_usage = _run_extraction_text(
        processed_text, schema, instructions, cache_buster
    )
    processed_elapsed = time.perf_counter() - start
    print(f"  elapsed_s: {processed_elapsed:.2f}")
    if processed_usage:
        print(f"  usage: {json.dumps(processed_usage)}")
    print(json.dumps(processed_result, indent=2))
    print("")
    print("LLM extraction (merged)")
    start = time.perf_counter()
    merged_result, merged_usage = _run_extraction_text(
        merged_text, schema, instructions, cache_buster
    )
    merged_elapsed = time.perf_counter() - start
    print(f"  elapsed_s: {merged_elapsed:.2f}")
    if merged_usage:
        print(f"  usage: {json.dumps(merged_usage)}")
    print(json.dumps(merged_result, indent=2))
    print("")
    print("LLM extraction (direct image)")
    start = time.perf_counter()
    image_result, image_usage = _run_extraction_direct_image(
        file_bytes, schema, instructions, cache_buster
    )
    image_elapsed = time.perf_counter() - start
    print(f"  image_count: {image_count}")
    print(f"  elapsed_s: {image_elapsed:.2f}")
    if image_usage:
        print(f"  usage: {json.dumps(image_usage)}")
    print(json.dumps(image_result, indent=2))


if __name__ == "__main__":
    main()
