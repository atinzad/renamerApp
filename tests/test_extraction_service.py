import json

from app.adapters.sqlite_storage import SQLiteStorage
from app.domain.labels import MATCHED
from app.domain.models import FileRef
from app.ports.llm_port import LLMPort
from app.services.extraction_service import ExtractionService


class DummyLLM(LLMPort):
    def __init__(self) -> None:
        self.image_calls: list[tuple[dict, bytes, str, str | None]] = []

    def classify_label(self, ocr_text, candidates):  # pragma: no cover
        raise NotImplementedError

    def extract_fields(
        self, schema: dict, ocr_text: str, instructions: str | None = None
    ) -> dict:
        _ = schema
        _ = ocr_text
        _ = instructions
        return {}

    def extract_fields_from_image(
        self,
        schema: dict,
        file_bytes: bytes,
        mime_type: str,
        instructions: str | None = None,
    ) -> dict:
        self.image_calls.append((schema, file_bytes, mime_type, instructions))
        return {"civil_id": "123", "birth_date": "1995-08-07"}


class DummyDrive:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def list_folder_files(self, folder_id: str):  # pragma: no cover
        raise NotImplementedError

    def download_file_bytes(self, file_id: str) -> bytes:
        self.calls.append(file_id)
        return self.payload

    def rename_file(self, file_id: str, new_name: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def upload_text_file(
        self, folder_id: str, filename: str, content: str
    ) -> str:  # pragma: no cover
        raise NotImplementedError


def test_extraction_service_stores_fields(tmp_path) -> None:
    storage = SQLiteStorage(str(tmp_path / "test.db"))
    job = storage.create_job("folder-1")
    storage.save_job_files(
        job.job_id,
        [FileRef(file_id="file-1", name="a", mime_type="image/png", sort_index=1)],
    )
    label_schema = json.dumps(
        {"type": "object", "properties": {"civil_id": {"type": "string"}}}
    )
    label = storage.create_label("Civil_ID", label_schema, "")
    storage.upsert_file_label_assignment(
        job.job_id, "file-1", label.label_id, 1.0, MATCHED
    )
    llm = DummyLLM()
    drive = DummyDrive(payload=b"fake-image-bytes")
    service = ExtractionService(llm, storage, drive)
    service.extract_fields_for_job(job.job_id)
    extraction = storage.get_extraction(job.job_id, "file-1")
    assert extraction is not None
    payload = json.loads(extraction.fields_json or "{}")
    assert payload["fields"]["civil_id"] == "123"
    assert payload["needs_review"] is False
    assert drive.calls == ["file-1"]
    assert len(llm.image_calls) == 1
    assert llm.image_calls[0][1] == b"fake-image-bytes"
    assert llm.image_calls[0][2] == "image/png"
