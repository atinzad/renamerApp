from datetime import datetime
from unittest.mock import Mock

import pytest

from app.domain.models import FileRef, Job
from app.services.jobs_service import JobsService


def test_create_job_saves_files() -> None:
    job = Job(
        job_id="job-1",
        folder_id="folder-1",
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        status="CREATED",
    )
    files = [FileRef(file_id="file-1", name="a.jpg", mime_type="image/jpeg")]
    storage = Mock()
    storage.create_job.return_value = job
    storage.get_job.return_value = job
    drive = Mock()
    drive.list_folder_files.return_value = files

    service = JobsService(drive=drive, storage=storage)
    result = service.create_job(job.folder_id)

    assert result == job
    drive.list_folder_files.assert_called_once_with(job.folder_id)
    storage.save_job_files.assert_called_once_with(job.job_id, files)
    storage.hydrate_job_cached_data.assert_called_once_with(
        job.job_id, [file_ref.file_id for file_ref in files]
    )


def test_refresh_job_files_updates_listing_for_target_folder() -> None:
    job = Job(
        job_id="job-1",
        folder_id="root-folder",
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        status="CREATED",
    )
    files = [FileRef(file_id="file-1", name="a.jpg", mime_type="image/jpeg")]
    storage = Mock()
    storage.get_job.return_value = job
    drive = Mock()
    drive.list_folder_files.return_value = files

    service = JobsService(drive=drive, storage=storage)
    result = service.refresh_job_files(job.job_id, folder_id="child-folder")

    assert result == files
    drive.list_folder_files.assert_called_once_with("child-folder")
    storage.save_job_files.assert_called_once_with(job.job_id, files)
    storage.hydrate_job_cached_data.assert_called_once_with(
        job.job_id, [file_ref.file_id for file_ref in files]
    )


def test_refresh_job_files_uses_job_root_when_folder_not_provided() -> None:
    job = Job(
        job_id="job-1",
        folder_id="root-folder",
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        status="CREATED",
    )
    files = [FileRef(file_id="file-1", name="a.jpg", mime_type="image/jpeg")]
    storage = Mock()
    storage.get_job.return_value = job
    drive = Mock()
    drive.list_folder_files.return_value = files

    service = JobsService(drive=drive, storage=storage)
    result = service.refresh_job_files(job.job_id)

    assert result == files
    drive.list_folder_files.assert_called_once_with(job.folder_id)


def test_list_files_missing_job_raises() -> None:
    storage = Mock()
    storage.get_job.return_value = None
    drive = Mock()
    service = JobsService(drive=drive, storage=storage)

    with pytest.raises(RuntimeError, match="Job not found"):
        service.list_files("missing-job")


def test_list_files_returns_files() -> None:
    job = Job(
        job_id="job-1",
        folder_id="folder-1",
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        status="CREATED",
    )
    files = [FileRef(file_id="file-1", name="a.jpg", mime_type="image/jpeg")]
    storage = Mock()
    storage.get_job.return_value = job
    storage.get_job_files.return_value = files
    drive = Mock()

    service = JobsService(drive=drive, storage=storage)
    result = service.list_files(job.job_id)

    assert result == files
