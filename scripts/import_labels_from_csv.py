from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

from dotenv import load_dotenv

from app.adapters.embeddings_dummy import DummyEmbeddingsAdapter
from app.adapters.google_drive_adapter import GoogleDriveAdapter
from app.adapters.ocr_tesseract_adapter import TesseractOCRAdapter
from app.adapters.sqlite_storage import SQLiteStorage
from app.services.label_service import LabelService


def _load_env(repo_root: Path) -> None:
    load_dotenv(repo_root / ".env", override=False)


def _normalize_header(value: str) -> str:
    return value.replace("\ufeff", "").strip()


def _load_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames:
            reader.fieldnames = [_normalize_header(name) for name in reader.fieldnames]
        rows: list[dict[str, str]] = []
        for row in reader:
            normalized = {}
            for key, value in row.items():
                normalized[_normalize_header(key)] = (value or "").strip()
            rows.append(normalized)
        return rows


def _ensure_label(label_service: LabelService, name: str, existing: dict[str, str]) -> str:
    label_id = existing.get(name)
    if label_id:
        return label_id
    label = label_service.create_label(name, "{}", "")
    existing[name] = label.label_id
    return label.label_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Import labels from CSV and seed a new DB.")
    parser.add_argument("--csv", required=True, help="Path to CSV with file_id,name,Label")
    parser.add_argument(
        "--sqlite",
        default=str(Path(__file__).resolve().parents[1] / "app_new.db"),
        help="Path to output sqlite DB (default: ./app_new.db)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    _load_env(repo_root)

    token = os.getenv("GOOGLE_DRIVE_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("GOOGLE_DRIVE_ACCESS_TOKEN is required in .env")

    csv_path = Path(args.csv)
    sqlite_path = Path(args.sqlite)

    storage = SQLiteStorage(str(sqlite_path))
    drive = GoogleDriveAdapter(token)
    ocr = TesseractOCRAdapter()
    embeddings = DummyEmbeddingsAdapter()
    label_service = LabelService(drive=drive, ocr=ocr, storage=storage, embeddings=embeddings)

    rows = _load_rows(csv_path)
    label_id_by_name: dict[str, str] = {
        label.name: label.label_id for label in storage.list_labels(include_inactive=True)
    }

    processed = 0
    skipped = 0
    for row in rows:
        file_id = row.get("file_id", "").strip()
        filename = row.get("name", "").strip()
        label_name = row.get("Label", "").strip()
        if not file_id or not label_name:
            skipped += 1
            continue

        display_name = filename or file_id
        print(f"[file] {display_name} ({file_id})")
        label_id = _ensure_label(label_service, label_name, label_id_by_name)
        if label_id_by_name.get(label_name) == label_id:
            print(f"[label] using existing label: {label_name}")
        else:
            print(f"[label] created new label: {label_name}")
        print("[ocr] downloading file bytes")
        file_bytes = drive.download_file_bytes(file_id)
        print("[ocr] running OCR")
        ocr_result = ocr.extract_text(file_bytes)
        storage.save_ocr_result("import", file_id, ocr_result)
        print("[label] attaching example to label")
        storage.attach_label_example(label_id, file_id, filename or file_id)
        print("[embeddings] processing label examples")
        label_service.process_examples(label_id, job_id=None)
        processed += 1

    print(f"Processed {processed} labeled rows; skipped {skipped} rows with no label.")


if __name__ == "__main__":
    main()
