from app.adapters.sqlite_storage import SQLiteStorage


def test_extraction_round_trip(tmp_path) -> None:
    storage = SQLiteStorage(str(tmp_path / "test.db"))
    storage.save_extraction(
        job_id="job-1",
        file_id="file-1",
        schema_json='{"type":"object"}',
        fields_json='{"id":"ABC"}',
        confidences_json='{"id":0.9}',
        updated_at="2024-01-01T00:00:00Z",
    )
    fetched = storage.get_extraction("job-1", "file-1")
    assert fetched == {
        "schema_json": '{"type":"object"}',
        "fields_json": '{"id":"ABC"}',
        "confidences_json": '{"id":0.9}',
        "updated_at": "2024-01-01T00:00:00Z",
    }
