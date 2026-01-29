from __future__ import annotations

import re


def merge_ocr_text(raw_text: str, preprocessed_text: str) -> str:
    raw_text = raw_text or ""
    preprocessed_text = preprocessed_text or ""
    parts: list[str] = []

    if preprocessed_text.strip():
        parts.append("PREPROCESSED_OCR\n" + preprocessed_text.strip())
    if raw_text.strip():
        parts.append("RAW_OCR\n" + raw_text.strip())

    numeric_tokens = _extract_numeric_tokens(raw_text, preprocessed_text)
    if numeric_tokens:
        parts.append("NUMERIC_TOKENS\n" + " ".join(numeric_tokens))

    numeric_lines = _extract_numeric_lines(raw_text)
    if numeric_lines:
        parts.append("RAW_NUMERIC_LINES\n" + "\n".join(numeric_lines))

    return "\n\n".join(parts).strip()


def _extract_numeric_tokens(*texts: str) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for text in texts:
        for match in re.findall(r"(?:\\d[\\s\\-]?){6,}", text or ""):
            compact = re.sub(r"\\D", "", match)
            if len(compact) < 6 or compact in seen:
                continue
            seen.add(compact)
            tokens.append(compact)
    return tokens


def _extract_numeric_lines(text: str) -> list[str]:
    lines = []
    for raw_line in (text or "").splitlines():
        digits = re.sub(r"\\D", "", raw_line)
        if len(digits) < 6:
            continue
        line = " ".join(raw_line.split())
        if line:
            lines.append(line)
    return lines
