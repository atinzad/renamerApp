from __future__ import annotations

from typing import Any

from app.adapters.google_drive_adapter import GoogleDriveAdapter
from app.adapters.sqlite_storage import SQLiteStorage
from app.services.jobs_service import JobsService
from app.services.report_service import ReportService
from app.services.rename_service import RenameService


def build_services(access_token: str, sqlite_path: str) -> dict[str, Any]:
    drive = GoogleDriveAdapter(access_token)
    storage = SQLiteStorage(sqlite_path)
    return {
        "jobs_service": JobsService(drive, storage),
        "rename_service": RenameService(drive, storage),
        "report_service": ReportService(drive, storage),
        "drive": drive,
        "storage": storage,
    }
