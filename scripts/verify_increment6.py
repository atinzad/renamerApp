from __future__ import annotations

import json
import os
from pathlib import Path

from app.container import build_services


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


def main() -> None:
    _load_env()
    access_token = os.getenv("GOOGLE_DRIVE_ACCESS_TOKEN")
    folder_id = os.getenv("FOLDER_ID")
    sqlite_path = os.getenv("TEST_SQLITE_PATH", "./app.db")
    if not access_token or not folder_id:
        raise SystemExit("Missing GOOGLE_DRIVE_ACCESS_TOKEN or FOLDER_ID in .env or environment.")

    services = build_services(access_token, sqlite_path)
    jobs_service = services["jobs_service"]
    ocr_service = services["ocr_service"]
    storage = services["storage"]
    extraction_service = services["extraction_service"]

    job = jobs_service.create_job(folder_id)
    files = jobs_service.list_files(job.job_id)
    if not files:
        raise SystemExit("No files returned from Drive for this folder.")

    ocr_service.run_ocr(job.job_id)
    first = next((file_ref for file_ref in files), None)
    if first is None:
        raise SystemExit("No files to extract.")
    ocr_result = storage.get_ocr_result(job.job_id, first.file_id)
    if ocr_result is None or not ocr_result.text.strip():
        raise SystemExit("Missing OCR text for the first file.")

    schema = {
        "type": "object",
        "properties": {
            "document_id": {"type": "string"},
            "birth_date": {"type": "string"},
        },
        "required": ["document_id", "birth_date"],
        "additionalProperties": False,
    }
    label = storage.create_label("EXTRACTION_TEST", json.dumps(schema), "")
    storage.update_label_extraction_instructions(
        label.label_id,
        'Extract fields according to this schema. If a field is missing, return "UNKNOWN".',
    )
    storage.upsert_file_label_override(job.job_id, first.file_id, label.label_id)

    extraction_service.extract_fields_for_job(job.job_id)
    extraction = storage.get_extraction(job.job_id, first.file_id)
    if extraction is None:
        raise SystemExit("No extraction stored for the first file.")
    payload = json.loads(extraction["fields_json"])
    fields = payload.get("fields", {})
    if not isinstance(fields, dict):
        raise SystemExit("Extraction fields are not a JSON object.")
    missing_keys = [key for key in schema["properties"].keys() if key not in fields]
    if missing_keys:
        raise SystemExit(f"Extraction missing keys: {missing_keys}")

    print("Increment 6 integration check passed.")
    print(f"job_id={job.job_id}")
    print(f"file_id={first.file_id}")
    print(f"label_id={label.label_id}")
    print(f"fields={fields}")


if __name__ == "__main__":
    main()
