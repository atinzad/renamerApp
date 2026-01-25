from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / ".env", override=False)

from app.container import build_services


def _get_updated_at(sqlite_path: str, job_id: str, file_id: str) -> str | None:
    try:
        with sqlite3.connect(sqlite_path) as conn:
            row = conn.execute(
                """
                SELECT updated_at
                FROM ocr_results
                WHERE job_id = ? AND file_id = ?
                """,
                (job_id, file_id),
            ).fetchone()
        if row is None:
            return None
        return row[0]
    except sqlite3.Error:
        return None


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
    report_service = services["report_service"]

    job = jobs_service.create_job(folder_id)
    files = jobs_service.list_files(job.job_id)
    if not files:
        raise SystemExit("No files returned from Drive for this folder.")
    if any(file_ref.mime_type == "text/plain" for file_ref in files):
        raise SystemExit("Found text/plain files in listing; expected them to be filtered out.")

    target_files = [
        file_ref
        for file_ref in files
        if file_ref.mime_type.startswith("image/") or file_ref.mime_type == "application/pdf"
    ]
    if not target_files:
        raise SystemExit("No image/PDF files found for OCR.")

    print(f"Job created: {job.job_id}")
    print(f"Files listed: {len(files)} (OCR targets: {len(target_files)})")

    print("Running OCR for all target files...")
    ocr_service.run_ocr(job.job_id)
    missing = [
        file_ref.file_id
        for file_ref in target_files
        if storage.get_ocr_result(job.job_id, file_ref.file_id) is None
    ]
    if missing:
        raise SystemExit(f"OCR results missing for: {missing}")

    first_file = target_files[0]
    before = _get_updated_at(sqlite_path, job.job_id, first_file.file_id)
    time.sleep(1)
    ocr_service.run_ocr(job.job_id, [first_file.file_id])
    after = _get_updated_at(sqlite_path, job.job_id, first_file.file_id)
    if before and after and before == after:
        raise SystemExit("OCR overwrite check failed: updated_at did not change.")

    report_text = report_service.preview_report(job.job_id)
    ocr_result = storage.get_ocr_result(job.job_id, first_file.file_id)
    if ocr_result and ocr_result.text.strip():
        snippet = ocr_result.text.strip()[:80]
        if snippet not in report_text:
            raise SystemExit("Report preview did not include OCR text snippet.")

    print("Integration checks passed.")
    print(f"Sample file: {first_file.name} ({first_file.file_id})")
    print(f"Sample OCR text length: {len(ocr_result.text) if ocr_result else 0}")


if __name__ == "__main__":
    main()
