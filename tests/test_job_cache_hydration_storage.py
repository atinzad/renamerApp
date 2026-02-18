from app.adapters.sqlite_storage import SQLiteStorage
from app.domain.doc_types import DocType, DocTypeClassification
from app.domain.models import FileRef


def test_hydrate_job_cached_data_copies_matching_file_state(tmp_path) -> None:
    storage = SQLiteStorage(str(tmp_path / "test.db"))

    source_job = storage.create_job("folder-1")
    storage.save_job_files(
        source_job.job_id,
        [FileRef(file_id="file-1", name="a.pdf", mime_type="application/pdf")],
    )

    storage.upsert_file_label_assignment(
        job_id=source_job.job_id,
        file_id="file-1",
        label_id="label-1",
        score=0.91,
        status="MATCHED",
    )
    storage.upsert_file_label_override(
        job_id=source_job.job_id,
        file_id="file-1",
        label_id="label-override",
    )
    storage.upsert_doc_type_classification(
        job_id=source_job.job_id,
        file_id="file-1",
        classification=DocTypeClassification(
            doc_type=DocType.OTHER,
            confidence=0.88,
            signals=["DOC_MATCH"],
        ),
        updated_at_iso="2025-01-01T00:00:00Z",
    )
    storage.set_doc_type_override(
        job_id=source_job.job_id,
        file_id="file-1",
        doc_type=DocType.OTHER,
        updated_at_iso="2025-01-01T00:00:01Z",
    )
    storage.upsert_llm_label_classification(
        job_id=source_job.job_id,
        file_id="file-1",
        label_name="Ownership",
        confidence=0.67,
        signals=["LLM_OK"],
        updated_at_iso="2025-01-01T00:00:02Z",
    )
    storage.set_llm_label_override(
        job_id=source_job.job_id,
        file_id="file-1",
        label_name="Ownership",
        updated_at_iso="2025-01-01T00:00:03Z",
    )
    storage.save_extraction(
        job_id=source_job.job_id,
        file_id="file-1",
        schema_json='{"type":"object","properties":{"name":{"type":"string"}}}',
        fields_json='{"fields":{"name":"Alice"}}',
        confidences_json='{"name":0.9}',
        updated_at="2025-01-01T00:00:04Z",
    )
    storage.upsert_file_timings(
        job_id=source_job.job_id,
        file_id="file-1",
        ocr_ms=100,
        classify_ms=200,
        extract_ms=300,
        updated_at_iso="2025-01-01T00:00:05Z",
    )

    target_job = storage.create_job("folder-1")
    storage.save_job_files(
        target_job.job_id,
        [
            FileRef(file_id="file-1", name="a.pdf", mime_type="application/pdf"),
            FileRef(file_id="file-2", name="b.pdf", mime_type="application/pdf"),
        ],
    )
    storage.hydrate_job_cached_data(target_job.job_id, ["file-1", "file-2"])

    assignment = storage.get_file_label_assignment(target_job.job_id, "file-1")
    assert assignment is not None
    assert assignment.label_id == "label-1"
    assert assignment.status == "MATCHED"
    assert assignment.score == 0.91
    assert storage.get_file_label_override(target_job.job_id, "file-1") == "label-override"

    doc_type = storage.get_doc_type_classification(target_job.job_id, "file-1")
    assert doc_type is not None
    assert doc_type.doc_type == DocType.OTHER
    assert doc_type.confidence == 0.88
    assert storage.get_doc_type_override(target_job.job_id, "file-1") == DocType.OTHER

    llm_classification = storage.get_llm_label_classification(target_job.job_id, "file-1")
    assert llm_classification is not None
    assert llm_classification.label_name == "Ownership"
    assert llm_classification.confidence == 0.67
    assert storage.get_llm_label_override(target_job.job_id, "file-1") == "Ownership"

    extraction = storage.get_extraction(target_job.job_id, "file-1")
    assert extraction is not None
    assert extraction.fields_json == '{"fields":{"name":"Alice"}}'

    timing = storage.get_file_timings(target_job.job_id, "file-1")
    assert timing is not None
    assert timing.ocr_ms == 100
    assert timing.classify_ms == 200
    assert timing.extract_ms == 300

    assert storage.get_file_label_assignment(target_job.job_id, "file-2") is None
    assert storage.get_extraction(target_job.job_id, "file-2") is None
