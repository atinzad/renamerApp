from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / ".env", override=False)

from app.container import build_services
from app.services.llm_fallback_label_service import LLMFallbackLabelService


def main() -> None:
    access_token = os.getenv("GOOGLE_DRIVE_ACCESS_TOKEN")
    folder_id = os.getenv("FOLDER_ID")
    sqlite_path = os.getenv("TEST_SQLITE_PATH", "./app.db")
    llm_provider = os.getenv("LLM_PROVIDER", "mock")
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if not access_token or not folder_id:
        raise SystemExit("Missing GOOGLE_DRIVE_ACCESS_TOKEN or FOLDER_ID in .env or environment.")
    if llm_provider == "mock" or (llm_provider == "openai" and not openai_key):
        raise SystemExit("LLM provider not configured (set LLM_PROVIDER and OPENAI_API_KEY).")

    services = build_services(access_token, sqlite_path)
    jobs_service = services["jobs_service"]
    ocr_service = services["ocr_service"]
    storage = services["storage"]
    llm = services["llm"]

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

    service = LLMFallbackLabelService(storage, llm)
    service.classify_unlabeled_files(job.job_id)

    stored = storage.get_llm_label_classification(job.job_id, first.file_id)
    if stored is None:
        raise SystemExit("No LLM fallback classification stored.")
    label_name, confidence, signals = stored
    labels = storage.list_labels(include_inactive=False)
    allowlist = {label.name for label in labels if label.llm}
    if label_name is not None and label_name not in allowlist:
        raise SystemExit("Stored label_name not in candidate allowlist.")

    print("Increment 5 integration check passed.")
    print(f"job_id={job.job_id}")
    print(f"file_id={first.file_id}")
    print(f"label_name={label_name}")
    print(f"confidence={confidence:.3f}")
    print(f"signals={signals}")


if __name__ == "__main__":
    main()
