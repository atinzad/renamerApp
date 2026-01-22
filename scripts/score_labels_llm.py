from __future__ import annotations

import argparse
import os
from pathlib import Path


def _load_env(env_path: str = ".env") -> None:
    path = Path(env_path)
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_env()

from app.adapters.llm_mock import MockLLMAdapter
from app.adapters.llm_openai import OpenAILLMAdapter
from app.adapters.sqlite_storage import SQLiteStorage
from app.domain.label_fallback import LabelFallbackCandidate


def _build_llm_adapter():
    from app.settings import (
        LLM_LABEL_MIN_CONFIDENCE,
        LLM_PROVIDER,
        OPENAI_API_KEY,
        OPENAI_BASE_URL,
        OPENAI_MODEL,
    )

    if LLM_PROVIDER.lower() == "openai" and OPENAI_API_KEY:
        return OpenAILLMAdapter(
            api_key=OPENAI_API_KEY,
            model=OPENAI_MODEL,
            base_url=OPENAI_BASE_URL,
            min_confidence=LLM_LABEL_MIN_CONFIDENCE,
        )
    return MockLLMAdapter()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr", required=True, help="Path to OCR text file.")
    parser.add_argument("--sqlite", default="./app.db", help="SQLite DB path.")
    args = parser.parse_args()

    ocr_text = Path(args.ocr).read_text()
    if not ocr_text.strip():
        raise SystemExit("OCR text file is empty.")

    storage = SQLiteStorage(args.sqlite)
    labels = [label for label in storage.list_labels(include_inactive=False) if label.llm]
    if not labels:
        raise SystemExit("No labels with non-empty LLM instructions.")

    llm = _build_llm_adapter()
    print("LLM label confidence per label:")
    for label in labels:
        candidate = LabelFallbackCandidate(
            name=label.name, instructions=label.llm
        )
        result = llm.classify_label(ocr_text, [candidate])
        print(f"- {label.name}")
        print(f"  confidence: {result.confidence}")
        print(f"  label_name: {result.label_name}")
        print(f"  signals: {result.signals}")


if __name__ == "__main__":
    main()
