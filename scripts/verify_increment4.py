from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / ".env", override=False)

from app.container import build_services
from app.domain.labels import MATCHED


def _example_label_map(storage, include_inactive: bool) -> dict[str, str]:
    file_to_label: dict[str, str] = {}
    labels = storage.list_labels(include_inactive=include_inactive)
    for label in labels:
        examples = storage.list_label_examples(label.label_id)
        for example in examples:
            file_to_label[example.file_id] = label.label_id
    return file_to_label


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
    label_service = services["label_service"]
    classifier = services["label_classification_service"]

    job = jobs_service.create_job(folder_id)
    files = jobs_service.list_files(job.job_id)
    if not files:
        raise SystemExit("No files returned from Drive for this folder.")

    ocr_service.run_ocr(job.job_id)
    files_with_ocr = [
        file_ref
        for file_ref in files
        if (
            (result := storage.get_ocr_result(job.job_id, file_ref.file_id))
            and result.text.strip()
        )
    ]
    if not files_with_ocr:
        raise SystemExit("No files with OCR text available for classification.")

    all_examples = _example_label_map(storage, include_inactive=True)
    active_examples = _example_label_map(storage, include_inactive=False)

    target_file = next(
        (file_ref for file_ref in files_with_ocr if file_ref.file_id not in all_examples),
        None,
    )
    expected_label_id = None
    label_origin = ""
    if target_file is not None:
        label_name = f"VERIFY_INCREMENT4_{uuid4().hex[:8]}"
        label = label_service.create_label(label_name, "{}", "")
        label_service.attach_example(label.label_id, target_file.file_id)
        label_service.process_examples(label.label_id, job_id=job.job_id)
        expected_label_id = label.label_id
        label_origin = "created"
    else:
        target_file = next(
            (file_ref for file_ref in files_with_ocr if file_ref.file_id in active_examples),
            None,
        )
        if target_file is None:
            raise SystemExit(
                "All OCR files are already attached to inactive labels. "
                "Use a fresh SQLite DB or add files not used as prior examples."
            )
        expected_label_id = active_examples[target_file.file_id]
        label_origin = "existing"

    details = classifier.classify_file(job.job_id, target_file.file_id)
    assignment = storage.get_file_label_assignment(job.job_id, target_file.file_id)
    if assignment is None:
        raise SystemExit("Classification did not persist an assignment.")
    status = assignment.status
    label_id = assignment.label_id
    score = float(assignment.score)
    if status != MATCHED:
        raise SystemExit(
            f"Classification status is {status}; expected {MATCHED}. details={details}"
        )
    if label_id != expected_label_id:
        raise SystemExit(
            f"Classification label mismatch. expected={expected_label_id} got={label_id}"
        )

    print("Increment 4 integration check passed.")
    print(f"job_id={job.job_id}")
    print(f"file_id={target_file.file_id}")
    print(f"label_id={label_id}")
    print(f"label_origin={label_origin}")
    print(f"score={score:.3f}")
    print(f"status={status}")


if __name__ == "__main__":
    main()
