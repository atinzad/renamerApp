from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from app.ports.drive_port import DrivePort
from app.ports.ocr_port import OCRPort
from app.ports.storage_port import StoragePort
from app.settings import OCR_WORKERS


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
                "mime_type": file_ref.mime_type,
                "sort_index": file_ref.sort_index if file_ref.sort_index is not None else index,
            }
            for index, file_ref in enumerate(job_files)
        ]
        if file_ids is None:
            target_rows = file_rows
        else:
            target_ids = {file_id for file_id in file_ids}
            target_rows = [row for row in file_rows if row["file_id"] in target_ids]

        image_rows = [
            row
            for row in target_rows
            if str(row.get("mime_type", "")).startswith("image/")
            or str(row.get("mime_type", "")) == "application/pdf"
        ]
        ordered_rows = sorted(
            image_rows,
            key=lambda row: (row["sort_index"], row["name"], row["file_id"]),
        )
        if OCR_WORKERS <= 1 or len(ordered_rows) <= 1:
            for row in ordered_rows:
                file_id = row["file_id"]
                image_bytes = self._drive.download_file_bytes(file_id)
                result = self._ocr.extract_text(image_bytes)
                self._storage.save_ocr_result(job_id, file_id, result)
            return

        payloads: list[tuple[str, bytes]] = []
        for row in ordered_rows:
            file_id = row["file_id"]
            image_bytes = self._drive.download_file_bytes(file_id)
            payloads.append((file_id, image_bytes))

        results: dict[str, object] = {}
        errors: list[tuple[str, Exception]] = []
        with ThreadPoolExecutor(max_workers=OCR_WORKERS) as executor:
            future_map = {
                executor.submit(self._ocr.extract_text, image_bytes): file_id
                for file_id, image_bytes in payloads
            }
            for future in as_completed(future_map):
                file_id = future_map[future]
                try:
                    results[file_id] = future.result()
                except Exception as exc:
                    errors.append((file_id, exc))

        if errors:
            file_id, exc = errors[0]
            raise RuntimeError(f"OCR failed for file {file_id}") from exc

        for row in ordered_rows:
            file_id = row["file_id"]
            result = results.get(file_id)
            if result is None:
                continue
            self._storage.save_ocr_result(job_id, file_id, result)
