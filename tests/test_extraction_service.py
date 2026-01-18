import json

from app.adapters.sqlite_storage import SQLiteStorage
from app.domain.models import FileRef, OCRResult
from app.domain.labels import MATCHED
from app.ports.llm_port import LLMPort
from app.services.extraction_service import ExtractionService


class DummyLLM(LLMPort):
    def classify_label(self, ocr_text, candidates):  # pragma: no cover
        raise NotImplementedError

    def extract_fields(self, schema: dict, ocr_text: str) -> dict:
        return {"civil_id": "123", "birth_date": "1995-08-07"}


def test_extraction_service_stores_fields(tmp_path) -> None:
    storage = SQLiteStorage(str(tmp_path / "test.db"))
    job = storage.create_job("folder-1")
    storage.save_job_files(
        job.job_id,
        [FileRef(file_id="file-1", name="a", mime_type="image/png", sort_index=1)],
    )
    label = storage.create_label("Civil_ID", "{}", "")
    storage.upsert_file_label_assignment(
        job.job_id, "file-1", label.label_id, 1.0, MATCHED
    )
    storage.save_ocr_result(job.job_id, "file-1", OCRResult(text="text", confidence=0.9))
    service = ExtractionService(DummyLLM(), storage)
    service.extract_fields_for_job(job.job_id)
    extraction = storage.get_extraction(job.job_id, "file-1")
    assert extraction is not None
    payload = json.loads(extraction["fields_json"])
    assert payload["fields"]["civil_id"] == "123"
    assert payload["needs_review"] is False
