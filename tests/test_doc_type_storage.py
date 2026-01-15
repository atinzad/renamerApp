from app.adapters.sqlite_storage import SQLiteStorage
from app.domain.doc_types import DocType, DocTypeClassification


def test_doc_type_classification_round_trip(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    storage = SQLiteStorage(str(db_path))

    classification = DocTypeClassification(
        doc_type=DocType.INVOICE,
        confidence=0.77,
        signals=["signal-1", "signal-2"],
    )
    storage.upsert_doc_type_classification(
        job_id="job-1",
        file_id="file-1",
        classification=classification,
        updated_at_iso="2025-01-01T12:00:00",
    )
    fetched = storage.get_doc_type_classification("job-1", "file-1")
    assert fetched == classification


def test_doc_type_classifications_list(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    storage = SQLiteStorage(str(db_path))

    storage.upsert_doc_type_classification(
        job_id="job-1",
        file_id="file-1",
        classification=DocTypeClassification(
            doc_type=DocType.CONTRACT, confidence=0.5, signals=[]
        ),
        updated_at_iso="2025-01-01T12:00:00",
    )
    storage.upsert_doc_type_classification(
        job_id="job-1",
        file_id="file-2",
        classification=DocTypeClassification(
            doc_type=DocType.CIVIL_ID, confidence=0.9, signals=["a"]
        ),
        updated_at_iso="2025-01-01T12:05:00",
    )

    results = storage.list_doc_type_classifications("job-1")
    assert set(results.keys()) == {"file-1", "file-2"}


def test_doc_type_overrides_round_trip(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    storage = SQLiteStorage(str(db_path))

    storage.set_doc_type_override(
        job_id="job-1",
        file_id="file-1",
        doc_type=DocType.OTHER,
        updated_at_iso="2025-01-01T12:00:00",
    )
    fetched = storage.get_doc_type_override("job-1", "file-1")
    assert fetched == DocType.OTHER

    results = storage.list_doc_type_overrides("job-1")
    assert results == {"file-1": DocType.OTHER}
