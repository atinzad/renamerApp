from __future__ import annotations

from app.domain.labels import Label, LabelExample
from app.domain.schema_validation import validate_schema_config
from app.domain.similarity import normalize_text_to_tokens
from app.ports.drive_port import DrivePort
from app.ports.embeddings_port import EmbeddingsPort
from app.ports.ocr_port import OCRPort
from app.ports.storage_port import StoragePort


class LabelService:
    def __init__(
        self,
        drive: DrivePort,
        ocr: OCRPort,
        embeddings: EmbeddingsPort,
        storage: StoragePort,
    ) -> None:
        self._drive = drive
        self._ocr = ocr
        self._embeddings = embeddings
        self._storage = storage

    def create_label(
        self, name: str, extraction_schema_json: str, naming_template: str
    ) -> Label:
        errors = validate_schema_config(extraction_schema_json, naming_template)
        if errors:
            raise ValueError("; ".join(errors))
        return self._storage.create_label(name, extraction_schema_json, naming_template)

    def deactivate_label(self, label_id: str) -> None:
        self._storage.deactivate_label(label_id)

    def list_labels(self) -> list[Label]:
        return self._storage.list_labels(include_inactive=False)

    def attach_example(self, label_id: str, file_id: str) -> LabelExample:
        filename = file_id
        return self._storage.attach_label_example(label_id, file_id, filename)

    def process_examples(self, label_id: str | None, job_id: str | None = None) -> None:
        if label_id is None:
            labels = self._storage.list_labels(include_inactive=True)
        else:
            label = self._storage.get_label(label_id)
            labels = [label] if label is not None else []
        for label in labels:
            examples = self._storage.list_label_examples(label.label_id)
            for example in examples:
                ocr_text = ""
                if job_id:
                    job_ocr = self._storage.get_ocr_result(job_id, example.file_id)
                    if job_ocr and job_ocr.text:
                        ocr_text = job_ocr.text
                if not ocr_text:
                    image_bytes = self._drive.download_file_bytes(example.file_id)
                    ocr_result = self._ocr.extract_text(image_bytes)
                    ocr_text = ocr_result.text
                embedding: list[float] | None = None
                token_fingerprint: set[str] | None = None
                try:
                    embedding = self._embeddings.embed_text(ocr_text)
                except Exception:
                    embedding = None
                if not embedding:
                    token_fingerprint = normalize_text_to_tokens(ocr_text)
                self._storage.save_label_example_features(
                    example.example_id,
                    ocr_text,
                    embedding if embedding else None,
                    token_fingerprint,
                )
