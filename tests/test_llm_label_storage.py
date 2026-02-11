from app.adapters.sqlite_storage import SQLiteStorage
from app.domain.models import LLMLabelClassification


def test_llm_label_classification_round_trip(tmp_path) -> None:
    storage = SQLiteStorage(str(tmp_path / "test.db"))
    storage.upsert_llm_label_classification(
        job_id="job-1",
        file_id="file-1",
        label_name="INVOICE",
        confidence=0.8,
        signals=["OK"],
        updated_at_iso="2024-01-01T00:00:00Z",
    )
    fetched = storage.get_llm_label_classification("job-1", "file-1")
    assert fetched == LLMLabelClassification(
        job_id="job-1",
        file_id="file-1",
        label_name="INVOICE",
        confidence=0.8,
        signals=["OK"],
        updated_at="2024-01-01T00:00:00Z",
    )


def test_llm_label_classifications_list(tmp_path) -> None:
    storage = SQLiteStorage(str(tmp_path / "test.db"))
    storage.upsert_llm_label_classification(
        job_id="job-1",
        file_id="file-1",
        label_name=None,
        confidence=0.2,
        signals=["ABSTAIN_NOT_ENOUGH_EVIDENCE"],
        updated_at_iso="2024-01-01T00:00:00Z",
    )
    storage.upsert_llm_label_classification(
        job_id="job-1",
        file_id="file-2",
        label_name="CIVIL_ID",
        confidence=0.9,
        signals=[],
        updated_at_iso="2024-01-01T00:00:01Z",
    )
    results = storage.list_llm_label_classifications("job-1")
    assert results == {
        "file-1": LLMLabelClassification(
            job_id="job-1",
            file_id="file-1",
            label_name=None,
            confidence=0.2,
            signals=["ABSTAIN_NOT_ENOUGH_EVIDENCE"],
            updated_at="2024-01-01T00:00:00Z",
        ),
        "file-2": LLMLabelClassification(
            job_id="job-1",
            file_id="file-2",
            label_name="CIVIL_ID",
            confidence=0.9,
            signals=[],
            updated_at="2024-01-01T00:00:01Z",
        ),
    }


def test_llm_label_overrides_round_trip(tmp_path) -> None:
    storage = SQLiteStorage(str(tmp_path / "test.db"))
    storage.set_llm_label_override(
        job_id="job-1",
        file_id="file-1",
        label_name="INVOICE",
        updated_at_iso="2024-01-01T00:00:00Z",
    )
    fetched = storage.get_llm_label_override("job-1", "file-1")
    assert fetched == "INVOICE"
    results = storage.list_llm_label_overrides("job-1")
    assert results == {"file-1": "INVOICE"}
    storage.clear_llm_label_override("job-1", "file-1")
    assert storage.get_llm_label_override("job-1", "file-1") is None
