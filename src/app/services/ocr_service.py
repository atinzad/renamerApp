from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from time import perf_counter

from app.ports.drive_port import DrivePort
from app.ports.ocr_port import OCRPort
from app.ports.storage_port import StoragePort
from app.settings import OCR_WORKERS


class OCRService:
    def __init__(self, drive: DrivePort, ocr: OCRPort, storage: StoragePort) -> None:
        self._drive = drive
        self._ocr = ocr
        self._storage = storage

    def run_ocr(
        self,
        job_id: str,
        file_ids: list[str] | None = None,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> None:
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
        skipped_cached = 0
        if file_ids is None:
            filtered_rows = []
            get_ocr = getattr(self._storage, "get_ocr_result", None)
            for row in ordered_rows:
                if callable(get_ocr):
                    existing = get_ocr(job_id, row["file_id"])
                    text = getattr(existing, "text", None)
                    if isinstance(text, str) and text.strip():
                        skipped_cached += 1
                        self._emit_progress(
                            progress_callback,
                            stage="skip_cached",
                            job_id=job_id,
                            file_id=row["file_id"],
                            file_name=row["name"],
                        )
                        continue
                filtered_rows.append(row)
            ordered_rows = filtered_rows
        ordered_rows = [
            {**row, "position": position}
            for position, row in enumerate(ordered_rows, start=1)
        ]
        run_mode = "serial" if OCR_WORKERS <= 1 or len(ordered_rows) <= 1 else "parallel"
        total = len(ordered_rows)
        self._emit_progress(
            progress_callback,
            stage="start",
            job_id=job_id,
            mode=run_mode,
            total=total,
            skipped_cached=skipped_cached,
        )
        if total == 0:
            self._emit_progress(
                progress_callback,
                stage="complete",
                job_id=job_id,
                total=0,
                processed=0,
                skipped_cached=skipped_cached,
            )
            return
        processed_count = 0
        if run_mode == "serial":
            for row in ordered_rows:
                file_id = row["file_id"]
                file_name = row["name"]
                row_position = row["position"]
                self._emit_progress(
                    progress_callback,
                    stage="download_started",
                    job_id=job_id,
                    file_id=file_id,
                    file_name=file_name,
                    index=row_position,
                    total=total,
                )
                started = perf_counter()
                image_bytes = self._drive.download_file_bytes(file_id)
                self._emit_progress(
                    progress_callback,
                    stage="download_done",
                    job_id=job_id,
                    file_id=file_id,
                    file_name=file_name,
                    bytes_len=len(image_bytes),
                    index=row_position,
                    total=total,
                )
                self._emit_progress(
                    progress_callback,
                    stage="ocr_started",
                    job_id=job_id,
                    file_id=file_id,
                    file_name=file_name,
                    index=row_position,
                    total=total,
                )
                result = self._ocr.extract_text(image_bytes)
                self._emit_progress(
                    progress_callback,
                    stage="ocr_done",
                    job_id=job_id,
                    file_id=file_id,
                    file_name=file_name,
                    text_len=len(getattr(result, "text", "") or ""),
                    index=row_position,
                    total=total,
                )
                self._emit_progress(
                    progress_callback,
                    stage="save_started",
                    job_id=job_id,
                    file_id=file_id,
                    file_name=file_name,
                    index=row_position,
                    total=total,
                )
                self._storage.save_ocr_result(job_id, file_id, result)
                duration_ms = int((perf_counter() - started) * 1000)
                self._storage.upsert_file_timings(
                    job_id=job_id,
                    file_id=file_id,
                    ocr_ms=duration_ms,
                    classify_ms=None,
                    extract_ms=None,
                    updated_at_iso=datetime.now(timezone.utc).isoformat(),
                )
                processed_count += 1
                self._emit_progress(
                    progress_callback,
                    stage="save_done",
                    job_id=job_id,
                    file_id=file_id,
                    file_name=file_name,
                    duration_ms=duration_ms,
                    processed=processed_count,
                    total=total,
                    index=row_position,
                )
            self._emit_progress(
                progress_callback,
                stage="complete",
                job_id=job_id,
                total=total,
                processed=processed_count,
                skipped_cached=skipped_cached,
            )
            return

        payloads: list[tuple[str, str, bytes, int]] = []
        for row in ordered_rows:
            file_id = row["file_id"]
            file_name = row["name"]
            row_position = row["position"]
            self._emit_progress(
                progress_callback,
                stage="download_started",
                job_id=job_id,
                file_id=file_id,
                file_name=file_name,
                index=row_position,
                total=total,
            )
            image_bytes = self._drive.download_file_bytes(file_id)
            self._emit_progress(
                progress_callback,
                stage="download_done",
                job_id=job_id,
                file_id=file_id,
                file_name=file_name,
                bytes_len=len(image_bytes),
                index=row_position,
                total=total,
            )
            payloads.append((file_id, file_name, image_bytes, row_position))

        results: dict[str, object] = {}
        timings_ms: dict[str, int] = {}
        errors: list[tuple[str, str, Exception]] = []
        with ThreadPoolExecutor(max_workers=OCR_WORKERS) as executor:
            future_map = {
                executor.submit(self._ocr.extract_text, image_bytes): (
                    file_id,
                    file_name,
                    row_position,
                    perf_counter(),
                )
                for file_id, file_name, image_bytes, row_position in payloads
            }
            for file_id, file_name, _, row_position in payloads:
                self._emit_progress(
                    progress_callback,
                    stage="ocr_started",
                    job_id=job_id,
                    file_id=file_id,
                    file_name=file_name,
                    index=row_position,
                    total=total,
                )
            for future in as_completed(future_map):
                file_id, file_name, row_position, started = future_map[future]
                try:
                    result = future.result()
                    results[file_id] = result
                    timings_ms[file_id] = int((perf_counter() - started) * 1000)
                    self._emit_progress(
                        progress_callback,
                        stage="ocr_done",
                        job_id=job_id,
                        file_id=file_id,
                        file_name=file_name,
                        text_len=len(getattr(result, "text", "") or ""),
                        index=row_position,
                        total=total,
                    )
                except Exception as exc:
                    errors.append((file_id, file_name, exc))
                    self._emit_progress(
                        progress_callback,
                        stage="ocr_failed",
                        job_id=job_id,
                        file_id=file_id,
                        file_name=file_name,
                        index=row_position,
                        total=total,
                        message=str(exc),
                    )

        if errors:
            file_id, file_name, exc = errors[0]
            self._emit_progress(
                progress_callback,
                stage="error",
                job_id=job_id,
                file_id=file_id,
                file_name=file_name,
                message=f"OCR failed for file {file_id}",
            )
            raise RuntimeError(f"OCR failed for file {file_id}") from exc

        for row in ordered_rows:
            file_id = row["file_id"]
            file_name = row["name"]
            row_position = row["position"]
            result = results.get(file_id)
            if result is None:
                continue
            self._emit_progress(
                progress_callback,
                stage="save_started",
                job_id=job_id,
                file_id=file_id,
                file_name=file_name,
                index=row_position,
                total=total,
            )
            self._storage.save_ocr_result(job_id, file_id, result)
            duration_ms = timings_ms.get(file_id)
            if duration_ms is not None:
                self._storage.upsert_file_timings(
                    job_id=job_id,
                    file_id=file_id,
                    ocr_ms=duration_ms,
                    classify_ms=None,
                    extract_ms=None,
                    updated_at_iso=datetime.now(timezone.utc).isoformat(),
                )
            processed_count += 1
            self._emit_progress(
                progress_callback,
                stage="save_done",
                job_id=job_id,
                file_id=file_id,
                file_name=file_name,
                duration_ms=duration_ms,
                processed=processed_count,
                total=total,
                index=row_position,
            )
        self._emit_progress(
            progress_callback,
            stage="complete",
            job_id=job_id,
            total=total,
            processed=processed_count,
            skipped_cached=skipped_cached,
        )

    @staticmethod
    def _emit_progress(
        callback: Callable[[dict], None] | None,
        **payload: object,
    ) -> None:
        if callback is None:
            return
        callback(dict(payload))
