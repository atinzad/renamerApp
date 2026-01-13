from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app.domain.models import Job, RenameOp, UndoLog
from app.services.rename_service import RenameService


def test_apply_rename_saves_undo_and_renames() -> None:
    job = Job(
        job_id="job-1",
        folder_id="folder-1",
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        status="CREATED",
    )
    ops = [
        RenameOp(file_id="file-1", old_name="a.jpg", new_name="b.jpg"),
        RenameOp(file_id="file-2", old_name="c.jpg", new_name="d.jpg"),
    ]
    storage = Mock()
    storage.get_job.return_value = job
    drive = Mock()

    service = RenameService(drive=drive, storage=storage)
    service.apply_rename(job.job_id, ops)

    storage.save_undo_log.assert_called_once()
    undo_arg = storage.save_undo_log.call_args.args[0]
    assert isinstance(undo_arg, UndoLog)
    assert undo_arg.job_id == job.job_id
    assert undo_arg.ops == ops

    assert drive.rename_file.call_args_list == [
        ((ops[0].file_id, ops[0].new_name),),
        ((ops[1].file_id, ops[1].new_name),),
    ]


def test_apply_rename_missing_job_raises() -> None:
    storage = Mock()
    storage.get_job.return_value = None
    drive = Mock()
    service = RenameService(drive=drive, storage=storage)

    with pytest.raises(RuntimeError, match="Job not found"):
        service.apply_rename("missing-job", [])


def test_undo_last_renames_in_reverse_and_clears() -> None:
    job = Job(
        job_id="job-1",
        folder_id="folder-1",
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        status="CREATED",
    )
    ops = [
        RenameOp(file_id="file-1", old_name="a.jpg", new_name="b.jpg"),
        RenameOp(file_id="file-2", old_name="c.jpg", new_name="d.jpg"),
    ]
    undo_log = UndoLog(job_id=job.job_id, created_at=datetime.now(timezone.utc), ops=ops)
    storage = Mock()
    storage.get_job.return_value = job
    storage.get_last_undo_log.return_value = undo_log
    drive = Mock()

    service = RenameService(drive=drive, storage=storage)
    service.undo_last(job.job_id)

    assert drive.rename_file.call_args_list == [
        ((ops[1].file_id, ops[1].old_name),),
        ((ops[0].file_id, ops[0].old_name),),
    ]
    storage.clear_last_undo_log.assert_called_once_with(job.job_id)


def test_undo_last_missing_log_raises() -> None:
    job = Job(
        job_id="job-1",
        folder_id="folder-1",
        created_at=datetime(2025, 1, 1, 12, 0, 0),
        status="CREATED",
    )
    storage = Mock()
    storage.get_job.return_value = job
    storage.get_last_undo_log.return_value = None
    drive = Mock()
    service = RenameService(drive=drive, storage=storage)

    with pytest.raises(RuntimeError, match="No undo log found"):
        service.undo_last(job.job_id)
