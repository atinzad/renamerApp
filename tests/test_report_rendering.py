from app.domain.report_rendering import render_increment2_report


def test_rendering_order_and_format() -> None:
    files = [
        {"sort_index": 2, "name": "b.png", "file_id": "f2", "mime_type": "image/png"},
        {"sort_index": 1, "name": "a.jpg", "file_id": "f1", "mime_type": "image/jpeg"},
        {"sort_index": 1, "name": "a.jpg", "file_id": "f0", "mime_type": "image/jpeg"},
    ]
    output = render_increment2_report(
        job_id="job-123",
        folder_id="folder-abc",
        generated_at_local_iso="2025-01-01T12:00:00",
        files=files,
    )

    lines = output.splitlines()
    assert lines[0] == "REPORT_VERSION: 1"
    assert lines[1] == "JOB_ID: job-123"
    assert lines[2] == "FOLDER_ID: folder-abc"
    assert lines[3] == "GENERATED_AT: 2025-01-01T12:00:00"

    blocks = output.split("--- FILE START ---")
    assert len(blocks) - 1 == 3

    expected_order = [
        ("1", "a.jpg", "f0"),
        ("2", "a.jpg", "f1"),
        ("3", "b.png", "f2"),
    ]
    for block, expected in zip(blocks[1:], expected_order, strict=True):
        index, name, file_id = expected
        assert f"INDEX: {index}" in block
        assert f"FILE_NAME: {name}" in block
        assert f"FILE_ID: {file_id}" in block
        assert "--- FILE END ---" in block
        assert "EXTRACTED_TEXT:\n<<<PENDING_EXTRACTION>>>" in block
        assert "EXTRACTED_FIELDS_JSON:\n<<<PENDING_EXTRACTION>>>" in block

    assert output.endswith("\n")
