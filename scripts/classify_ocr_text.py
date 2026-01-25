from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / ".env", override=False)

from app.adapters.embeddings_dummy import DummyEmbeddingsAdapter
from app.adapters.llm_mock import MockLLMAdapter
from app.adapters.llm_openai import OpenAILLMAdapter
from app.adapters.sqlite_storage import SQLiteStorage
from app.domain.models import FileRef, OCRResult


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


def _write_labels_json(labels: list[dict]) -> Path:
    temp_dir = Path(tempfile.mkdtemp())
    path = temp_dir / "labels.json"
    path.write_text(json.dumps(labels, indent=2, sort_keys=True))
    return path


def main() -> None:
    from app.services.label_classification_service import LabelClassificationService
    from app.services.llm_fallback_label_service import LLMFallbackLabelService

    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr", required=True, help="Path to OCR text file.")
    parser.add_argument("--sqlite", default="./app.db", help="SQLite DB path.")
    args = parser.parse_args()

    ocr_text = Path(args.ocr).read_text()
    if not ocr_text.strip():
        raise SystemExit("OCR text file is empty.")

    storage = SQLiteStorage(args.sqlite)
    job = storage.create_job("local")
    file_id = f"local-{uuid4()}"
    storage.save_job_files(
        job.job_id,
        [FileRef(file_id=file_id, name="ocr.txt", mime_type="text/plain", sort_index=0)],
    )
    storage.save_ocr_result(job.job_id, file_id, OCRResult(text=ocr_text, confidence=1.0))

    classifier = LabelClassificationService(DummyEmbeddingsAdapter(), storage)
    classifier.classify_file(job.job_id, file_id)
    assignment = storage.get_file_label_assignment(job.job_id, file_id)
    label_name = None
    if assignment and assignment.get("label_id"):
        label = storage.get_label(assignment["label_id"])
        label_name = label.name if label else None

    print("Rule-based classification:")
    if assignment:
        print(
            json.dumps(
                {
                    "label_name": label_name,
                    "score": assignment.get("score", 0.0),
                    "status": assignment.get("status"),
                },
                indent=2,
            )
        )
    else:
        print(json.dumps({"label_name": None, "score": 0.0, "status": "NO_MATCH"}, indent=2))

    labels = [
        {"name": label.name, "examples": [], "llm": label.llm or ""}
        for label in storage.list_labels(include_inactive=False)
    ]
    labels_path = _write_labels_json(labels)
    llm = _build_llm_adapter()
    llm_service = LLMFallbackLabelService(storage, llm, labels_path=labels_path)
    try:
        llm_service.classify_file(job.job_id, file_id)
    except RuntimeError as exc:
        print(f"LLM fallback classification skipped: {exc}")
        return

    llm_result = storage.get_llm_label_classification(job.job_id, file_id)
    print("LLM fallback classification:")
    if llm_result is None:
        print(json.dumps({"label_name": None, "confidence": 0.0, "signals": []}, indent=2))
    else:
        label_name, confidence, signals = llm_result
        print(
            json.dumps(
                {
                    "label_name": label_name,
                    "confidence": confidence,
                    "signals": signals,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
