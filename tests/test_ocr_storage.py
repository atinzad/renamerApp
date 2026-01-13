from app.adapters.sqlite_storage import SQLiteStorage
from app.domain.models import OCRResult


def test_save_and_get_ocr_result_overwrites(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    storage = SQLiteStorage(str(db_path))

    job_id = "job-1"
    file_id = "file-1"
    first = OCRResult(text="first", confidence=0.5)
    second = OCRResult(text="second", confidence=0.9)

    storage.save_ocr_result(job_id, file_id, first)
    fetched = storage.get_ocr_result(job_id, file_id)
    assert fetched == first

    storage.save_ocr_result(job_id, file_id, second)
    fetched_again = storage.get_ocr_result(job_id, file_id)
    assert fetched_again == second
