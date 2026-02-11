from unittest.mock import Mock

from app.domain.models import FileRef, OCRResult
from app.services.label_classification_service import LabelClassificationService


def test_classify_skips_when_override_exists() -> None:
    storage = Mock()
    storage.get_job_files.return_value = [
        FileRef(file_id="file-1", name="a.jpg", mime_type="image/jpeg", sort_index=0)
    ]
    storage.list_labels.return_value = []
    storage.get_file_label_override.return_value = "label-1"
    service = LabelClassificationService(embeddings=Mock(), storage=storage)

    service.classify_job_files("job-1")

    storage.upsert_file_label_assignment.assert_not_called()


def test_classify_missing_ocr_no_match() -> None:
    storage = Mock()
    storage.get_job_files.return_value = [
        FileRef(file_id="file-1", name="a.jpg", mime_type="image/jpeg", sort_index=0)
    ]
    storage.list_labels.return_value = []
    storage.get_file_label_override.return_value = None
    storage.get_ocr_result.return_value = None
    service = LabelClassificationService(embeddings=Mock(), storage=storage)

    service.classify_job_files("job-1")

    storage.upsert_file_label_assignment.assert_called_once()


def test_classify_embeddings_path() -> None:
    storage = Mock()
    storage.get_job_files.return_value = [
        FileRef(file_id="file-1", name="a.jpg", mime_type="image/jpeg", sort_index=0)
    ]
    storage.list_labels.return_value = [Mock(label_id="label-1")]
    storage.list_label_examples.return_value = [Mock(example_id="ex-1")]
    storage.get_file_label_override.return_value = None
    storage.get_ocr_result.return_value = OCRResult(text="sample", confidence=None)
    storage.get_label_example_features.return_value = {"embedding": [1.0, 0.0], "ocr_text": ""}
    embeddings = Mock()
    embeddings.embed_text.return_value = [1.0, 0.0]
    service = LabelClassificationService(embeddings=embeddings, storage=storage)

    service.classify_job_files("job-1")

    storage.upsert_file_label_assignment.assert_called_once()


def test_classify_lexical_path() -> None:
    storage = Mock()
    storage.get_job_files.return_value = [
        FileRef(file_id="file-1", name="a.jpg", mime_type="image/jpeg", sort_index=0)
    ]
    storage.list_labels.return_value = [Mock(label_id="label-1")]
    storage.list_label_examples.return_value = [Mock(example_id="ex-1")]
    storage.get_file_label_override.return_value = None
    storage.get_ocr_result.return_value = OCRResult(text="hello world", confidence=None)
    storage.get_label_example_features.return_value = {"token_fingerprint": {"hello"}}
    embeddings = Mock()
    embeddings.embed_text.side_effect = RuntimeError("Embeddings not configured")
    service = LabelClassificationService(embeddings=embeddings, storage=storage)

    service.classify_job_files("job-1")

    storage.upsert_file_label_assignment.assert_called_once()
