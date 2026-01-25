from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / ".env", override=False)

from app.adapters.sqlite_storage import SQLiteStorage
from app.container import build_services
from app.domain.labels import MATCHED, NO_MATCH, decide_match
from app.domain.similarity import jaccard_similarity, normalize_text_to_tokens


def _labels_path() -> Path:
    return Path(__file__).resolve().parents[1] / "labels.json"


def _save_labels(data: list[dict]) -> None:
    _labels_path().write_text(json.dumps(data, indent=2, sort_keys=True))


def _classify(labels: list[dict], ocr_text: str) -> tuple[str | None, float, str]:
    tokens = normalize_text_to_tokens(ocr_text)
    if not tokens or not labels:
        return None, 0.0, NO_MATCH
    scores: list[tuple[str, float]] = []
    for label in labels:
        name = label.get("name")
        examples = label.get("examples", [])
        if not name or not examples:
            continue
        best = None
        for example_text in examples:
            example_tokens = normalize_text_to_tokens(example_text)
            score = jaccard_similarity(tokens, example_tokens)
            if best is None or score > best:
                best = score
        if best is not None:
            scores.append((name, best))
    if not scores:
        return None, 0.0, NO_MATCH
    scores.sort(key=lambda item: item[1], reverse=True)
    best_label, best_score = scores[0]
    second_score = scores[1][1] if len(scores) > 1 else None
    status, _ = decide_match(best_label, best_score, second_score, 0.35, 0.02)
    return best_label, best_score, status


def main() -> None:
    access_token = os.getenv("GOOGLE_DRIVE_ACCESS_TOKEN")
    folder_id = os.getenv("FOLDER_ID")
    sqlite_path = os.getenv("TEST_SQLITE_PATH", "./app.db")
    if not access_token or not folder_id:
        raise SystemExit("Missing GOOGLE_DRIVE_ACCESS_TOKEN or FOLDER_ID in .env or environment.")

    services = build_services(access_token, sqlite_path)
    jobs_service = services["jobs_service"]
    ocr_service = services["ocr_service"]
    storage = services["storage"]

    job = jobs_service.create_job(folder_id)
    files = jobs_service.list_files(job.job_id)
    if not files:
        raise SystemExit("No files returned from Drive for this folder.")

    ocr_service.run_ocr(job.job_id)
    first = next((file_ref for file_ref in files), None)
    if first is None:
        raise SystemExit("No files to classify.")
    ocr_result = storage.get_ocr_result(job.job_id, first.file_id)
    if ocr_result is None or not ocr_result.text.strip():
        raise SystemExit("Missing OCR text for the first file.")

    labels = [{"name": "TEST_LABEL", "examples": [ocr_result.text]}]
    _save_labels(labels)

    label, score, status = _classify(labels, ocr_result.text)
    if status != MATCHED or label != "TEST_LABEL":
        raise SystemExit("Classification did not match the expected label.")

    print("Increment 4 integration check passed.")
    print(f"job_id={job.job_id}")
    print(f"file_id={first.file_id}")
    print(f"label={label}")
    print(f"score={score:.3f}")
    print(f"status={status}")


if __name__ == "__main__":
    main()
