from __future__ import annotations

from app.domain.models import FileRef, Job
from app.ports.drive_port import DrivePort
from app.ports.storage_port import StoragePort


class JobsService:
    def __init__(self, drive: DrivePort, storage: StoragePort) -> None:
        self._drive = drive
        self._storage = storage

    def create_job(self, folder_id: str) -> Job:
        job = self._storage.create_job(folder_id)
        self.refresh_job_files(job.job_id, folder_id=folder_id)
        return job

    def list_files(self, job_id: str) -> list[FileRef]:
        job = self._storage.get_job(job_id)
        if job is None:
            raise RuntimeError(f"Job not found: {job_id}")
        return self._storage.get_job_files(job_id)

    def refresh_job_files(self, job_id: str, folder_id: str | None = None) -> list[FileRef]:
        job = self._storage.get_job(job_id)
        if job is None:
            raise RuntimeError(f"Job not found: {job_id}")
        target_folder_id = folder_id or job.folder_id
        files = self._drive.list_folder_files(target_folder_id)
        self._storage.save_job_files(job_id, files)
        self._storage.hydrate_job_cached_data(
            job_id, [file_ref.file_id for file_ref in files]
        )
        return files
