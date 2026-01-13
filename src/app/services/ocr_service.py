from __future__ import annotations

from app.ports.drive_port import DrivePort
from app.ports.ocr_port import OCRPort
from app.ports.storage_port import StoragePort


class OCRService:
    def __init__(self, drive: DrivePort, ocr: OCRPort, storage: StoragePort) -> None:
        self._drive = drive
        self._ocr = ocr
        self._storage = storage

    def run_ocr(self, job_id: str, file_ids: list[str] | None = None) -> None:
        job_files = self._storage.get_job_files(job_id)
        file_rows = [
            {
                "file_id": file_ref.file_id,
                "name": file_ref.name,
                "sort_index": file_ref.sort_index if file_ref.sort_index is not None else index,
            }
            for index, file_ref in enumerate(job_files)
        ]
        if file_ids is None:
            target_rows = file_rows
        else:
            target_ids = {file_id for file_id in file_ids}
            target_rows = [row for row in file_rows if row["file_id"] in target_ids]

        ordered_rows = sorted(
            target_rows,
            key=lambda row: (row["sort_index"], row["name"], row["file_id"]),
        )
        for row in ordered_rows:
            file_id = row["file_id"]
            image_bytes = self._drive.download_file_bytes(file_id)
            result = self._ocr.extract_text(image_bytes)
            self._storage.save_ocr_result(job_id, file_id, result)
