from __future__ import annotations

from typing import Any

from app.adapters.embeddings_dummy import DummyEmbeddingsAdapter
from app.adapters.google_drive_adapter import GoogleDriveAdapter
from app.adapters.ocr_tesseract_adapter import TesseractOCRAdapter
from app.adapters.sqlite_storage import SQLiteStorage
from app.settings import EMBEDDINGS_ENABLED
from app.services.jobs_service import JobsService
from app.services.ocr_service import OCRService
from app.services.report_service import ReportService
from app.services.rename_service import RenameService


def build_services(access_token: str, sqlite_path: str) -> dict[str, Any]:
    drive = GoogleDriveAdapter(access_token)
    ocr = TesseractOCRAdapter()
    embeddings = DummyEmbeddingsAdapter()
    if EMBEDDINGS_ENABLED:
        embeddings = DummyEmbeddingsAdapter()
    storage = SQLiteStorage(sqlite_path)
    return {
        "jobs_service": JobsService(drive, storage),
        "ocr_service": OCRService(drive, ocr, storage),
        "rename_service": RenameService(drive, storage),
        "report_service": ReportService(drive, storage),
        "drive": drive,
        "embeddings": embeddings,
        "ocr": ocr,
        "storage": storage,
    }
