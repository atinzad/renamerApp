from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.domain.label_fallback import LabelFallbackCandidate, LabelFallbackClassification
from app.domain.models import FileRef, OCRResult
from app.ports.llm_port import LLMPort
from app.services.llm_fallback_label_service import LLMFallbackLabelService


@dataclass(frozen=True)
class _LLMCall:
    text: str
    candidates: list[LabelFallbackCandidate]


class _RecordingLLM(LLMPort):
    def __init__(self, label_name: str | None, confidence: float, signals: list[str]) -> None:
        self._response = LabelFallbackClassification(
            label_name=label_name, confidence=confidence, signals=signals
        )
        self.calls: list[_LLMCall] = []

    def classify_label(
        self, ocr_text: str, candidates: list[LabelFallbackCandidate]
    ) -> LabelFallbackClassification:
        self.calls.append(_LLMCall(text=ocr_text, candidates=candidates))
        return self._response

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
        _ = schema
        _ = file_bytes
        _ = mime_type
        _ = instructions
        return {}


def _setup_job(storage) -> str:
    job = storage.create_job("folder")
    storage.save_job_files(
        job.job_id,
        [
            FileRef(file_id="file-1", name="a", mime_type="image/png"),
            FileRef(file_id="file-2", name="b", mime_type="image/png"),
        ],
    )
    storage.save_ocr_result(
        job.job_id,
        "file-1",
        OCRResult(text="invoice text", confidence=0.9),
    )
    storage.save_ocr_result(
        job.job_id,
        "file-2",
        OCRResult(text="id text", confidence=0.9),
    )
    return job.job_id


def test_fallback_service_requires_candidates(tmp_path, monkeypatch) -> None:
    storage = _storage(tmp_path)
    _seed_labels(storage, [{"name": "INVOICE", "llm": ""}])
    llm = _RecordingLLM(label_name=None, confidence=0.0, signals=[])
    service = LLMFallbackLabelService(storage, llm)
    _set_llm_config(monkeypatch, provider="openai", api_key="key")
    with pytest.raises(RuntimeError, match="No fallback labels configured"):
        service.classify_unlabeled_files("job-1")


def test_fallback_service_skips_overrides(tmp_path, monkeypatch) -> None:
    storage = _storage(tmp_path)
    _seed_labels(storage, [{"name": "INVOICE", "llm": "Find invoices."}])
    job_id = _setup_job(storage)
    storage.upsert_file_label_override(job_id, "file-1", "label-1")
    storage.set_llm_label_override(job_id, "file-2", "INVOICE", "2024-01-01T00:00:00Z")
    llm = _RecordingLLM(label_name="INVOICE", confidence=0.9, signals=[])
    service = LLMFallbackLabelService(storage, llm)
    _set_llm_config(monkeypatch, provider="openai", api_key="key")
    service.classify_unlabeled_files(job_id)
    assert llm.calls == []


def test_fallback_service_stores_results(tmp_path, monkeypatch) -> None:
    storage = _storage(tmp_path)
    _seed_labels(
        storage,
        [
            {"name": "INVOICE", "llm": "Find invoices."},
            {"name": "CIVIL_ID", "llm": "Find civil ids."},
        ],
    )
    job_id = _setup_job(storage)
    llm = _RecordingLLM(label_name="INVOICE", confidence=0.9, signals=["OK"])
    service = LLMFallbackLabelService(storage, llm)
    _set_llm_config(monkeypatch, provider="openai", api_key="key")
    service.classify_unlabeled_files(job_id)
    stored = storage.get_llm_label_classification(job_id, "file-1")
    assert stored is not None
    assert stored.label_name == "INVOICE"
    assert stored.confidence == 0.9
    assert stored.signals == ["OK"]


def test_fallback_service_skips_non_no_match(tmp_path, monkeypatch) -> None:
    storage = _storage(tmp_path)
    _seed_labels(storage, [{"name": "INVOICE", "llm": "Find invoices."}])
    job_id = _setup_job(storage)
    storage.upsert_file_label_assignment(
        job_id,
        "file-1",
        "label-1",
        0.9,
        "MATCHED",
    )
    llm = _RecordingLLM(label_name="INVOICE", confidence=0.9, signals=[])
    service = LLMFallbackLabelService(storage, llm)
    _set_llm_config(monkeypatch, provider="openai", api_key="key")
    service.classify_unlabeled_files(job_id)
    assert llm.calls == [
        _LLMCall(
            text="id text",
            candidates=[LabelFallbackCandidate(name="INVOICE", instructions="Find invoices.")],
        )
    ]


def test_fallback_service_requires_llm_config(tmp_path, monkeypatch) -> None:
    storage = _storage(tmp_path)
    _seed_labels(storage, [{"name": "INVOICE", "llm": "Find invoices."}])
    job_id = _setup_job(storage)
    llm = _RecordingLLM(label_name="INVOICE", confidence=0.9, signals=[])
    service = LLMFallbackLabelService(storage, llm)
    _set_llm_config(monkeypatch, provider="mock", api_key="")
    with pytest.raises(RuntimeError, match="LLM provider not configured"):
        service.classify_unlabeled_files(job_id)


def _storage(tmp_path):
    from app.adapters.sqlite_storage import SQLiteStorage

    return SQLiteStorage(str(tmp_path / "test.db"))


def _seed_labels(storage, labels: list[dict]) -> None:
    for label in labels:
        created = storage.create_label(label["name"], "{}", "")
        storage.update_label_llm(created.label_id, label.get("llm", ""))


def _set_llm_config(monkeypatch, provider: str, api_key: str) -> None:
    import app.services.llm_fallback_label_service as service_module

    monkeypatch.setattr(service_module, "LLM_PROVIDER", provider)
    monkeypatch.setattr(service_module, "OPENAI_API_KEY", api_key)
