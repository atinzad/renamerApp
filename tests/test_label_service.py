from unittest.mock import Mock

import pytest

from app.domain.labels import Label, LabelExample
from app.services.label_service import LabelService


def test_create_label_validates_schema() -> None:
    storage = Mock()
    storage.create_label.return_value = Label(
        label_id="label-1",
        name="Test",
        is_active=True,
        created_at=None,
        extraction_schema_json="{}",
        naming_template="",
    )
    service = LabelService(drive=Mock(), ocr=Mock(), embeddings=Mock(), storage=storage)

    result = service.create_label("Test", "{}", "")

    assert result.label_id == "label-1"
    storage.create_label.assert_called_once()


def test_create_label_invalid_schema_raises() -> None:
    storage = Mock()
    service = LabelService(drive=Mock(), ocr=Mock(), embeddings=Mock(), storage=storage)

    with pytest.raises(ValueError):
        service.create_label("Test", "{", "{Name}")


def test_attach_example_defaults_filename() -> None:
    storage = Mock()
    storage.attach_label_example.return_value = LabelExample(
        example_id="ex-1",
        label_id="label-1",
        file_id="file-1",
        filename="file-1",
        created_at=None,
    )
    service = LabelService(drive=Mock(), ocr=Mock(), embeddings=Mock(), storage=storage)

    example = service.attach_example("label-1", "file-1")

    assert example.filename == "file-1"
    storage.attach_label_example.assert_called_once_with("label-1", "file-1", "file-1")


def test_process_examples_embeddings_fallback_to_tokens() -> None:
    storage = Mock()
    storage.list_labels.return_value = [
        Label(
            label_id="label-1",
            name="Test",
            is_active=True,
            created_at=None,
            extraction_schema_json="{}",
            naming_template="",
        )
    ]
    storage.list_label_examples.return_value = [
        LabelExample(
            example_id="ex-1",
            label_id="label-1",
            file_id="file-1",
            filename="file-1",
            created_at=None,
        )
    ]
    storage.get_ocr_result.return_value = None
    drive = Mock()
    drive.download_file_bytes.return_value = b"img"
    ocr = Mock()
    ocr.extract_text.return_value = Mock(text="hello world")
    embeddings = Mock()
    embeddings.embed_text.side_effect = RuntimeError("Embeddings not configured")
    service = LabelService(drive=drive, ocr=ocr, embeddings=embeddings, storage=storage)

    service.process_examples(None)

    storage.save_label_example_features.assert_called_once()


def test_process_examples_reuses_job_ocr_text() -> None:
    storage = Mock()
    storage.list_labels.return_value = [
        Label(
            label_id="label-1",
            name="Test",
            is_active=True,
            created_at=None,
            extraction_schema_json="{}",
            naming_template="",
        )
    ]
    storage.list_label_examples.return_value = [
        LabelExample(
            example_id="ex-1",
            label_id="label-1",
            file_id="file-1",
            filename="file-1",
            created_at=None,
        )
    ]
    storage.get_ocr_result.return_value = Mock(text="cached text")
    drive = Mock()
    ocr = Mock()
    embeddings = Mock()
    embeddings.embed_text.return_value = []
    service = LabelService(drive=drive, ocr=ocr, embeddings=embeddings, storage=storage)

    service.process_examples(None, job_id="job-1")

    drive.download_file_bytes.assert_not_called()
    ocr.extract_text.assert_not_called()
    storage.save_label_example_features.assert_called_once()
