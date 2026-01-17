from app.domain.report_rendering import render_increment2_report
from app.domain.schema_utils import apply_missing_field_policy


def test_apply_missing_field_policy_fills_unknown() -> None:
    schema = {"type": "object", "properties": {"doc_id": {"type": "string"}}}
    fields, warnings, needs_review = apply_missing_field_policy(schema, {})
    assert fields["doc_id"] == "UNKNOWN"
    assert warnings == ["Missing required field: doc_id"]
    assert needs_review is True


def test_report_rendering_uses_extracted_fields_json() -> None:
    report = render_increment2_report(
        job_id="job-1",
        folder_id="folder-1",
        generated_at_local_iso="2024-01-01T00:00:00",
        files=[
            {
                "file_id": "file-1",
                "name": "a.png",
                "mime_type": "image/png",
                "sort_index": 0,
                "extracted_text": "",
                "extracted_fields": {"doc_id": "ABC"},
            }
        ],
    )
    assert "EXTRACTED_FIELDS_JSON:" in report
    assert '{"doc_id": "ABC"}' in report
