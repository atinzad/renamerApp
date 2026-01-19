from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.domain.label_fallback import (
    LabelFallbackCandidate,
    list_fallback_candidates,
    normalize_labels_llm,
)
from app.domain.labels import NO_MATCH
from app.ports.llm_port import LLMPort
from app.ports.storage_port import StoragePort
from app.settings import LLM_LABEL_MIN_CONFIDENCE, LLM_PROVIDER, OPENAI_API_KEY


@dataclass(frozen=True)
class LLMFallbackLabelResult:
    label_name: str | None
    confidence: float
    signals: list[str]


class LLMFallbackLabelService:
    def __init__(
        self,
        storage: StoragePort,
        llm: LLMPort,
        labels_path: Path | None = None,
    ) -> None:
        self._storage = storage
        self._llm = llm
        self._labels_path = labels_path or self._default_labels_path()

    def classify_unlabeled_files(self, job_id: str) -> None:
        candidates = self._load_fallback_candidates()
        if not candidates:
            raise RuntimeError("No fallback labels configured (labels with non-empty llm).")
        self._ensure_llm_configured()

        assignments = {
            item.get("file_id"): item
            for item in self._storage.list_file_label_assignments(job_id)
        }
        overrides = {
            item.get("file_id"): item
            for item in self._storage.list_file_label_overrides(job_id)
        }
        llm_overrides = self._storage.list_llm_label_overrides(job_id)

        for file_ref in self._storage.get_job_files(job_id):
            file_id = file_ref.file_id
            self._classify_file_for_job(
                job_id,
                file_id,
                candidates,
                assignments,
                overrides,
                llm_overrides,
            )

    def classify_file(self, job_id: str, file_id: str) -> None:
        candidates = self._load_fallback_candidates()
        if not candidates:
            raise RuntimeError("No fallback labels configured (labels with non-empty llm).")
        self._ensure_llm_configured()
        assignments = {
            item.get("file_id"): item
            for item in self._storage.list_file_label_assignments(job_id)
        }
        overrides = {
            item.get("file_id"): item
            for item in self._storage.list_file_label_overrides(job_id)
        }
        llm_overrides = self._storage.list_llm_label_overrides(job_id)
        self._classify_file_for_job(
            job_id,
            file_id,
            candidates,
            assignments,
            overrides,
            llm_overrides,
        )

    def _ensure_llm_configured(self) -> None:
        provider = LLM_PROVIDER.lower()
        if provider == "mock" or (provider == "openai" and not OPENAI_API_KEY):
            raise RuntimeError("LLM provider not configured. Set LLM_PROVIDER and OPENAI_API_KEY.")

    def _classify_file_for_job(
        self,
        job_id: str,
        file_id: str,
        candidates: list[LabelFallbackCandidate],
        assignments: dict[str, dict],
        overrides: dict[str, dict],
        llm_overrides: dict[str, str],
    ) -> None:
        if file_id in overrides:
            return
        if file_id in llm_overrides:
            return
        assignment = assignments.get(file_id)
        if assignment is not None and assignment.get("status") != NO_MATCH:
            return
        ocr = self._storage.get_ocr_result(job_id, file_id)
        if ocr is None or not ocr.text:
            return
        result = self._classify_file(ocr.text, candidates)
        updated_at = datetime.now(timezone.utc).isoformat()
        self._storage.upsert_llm_label_classification(
            job_id,
            file_id,
            result.label_name,
            result.confidence,
            result.signals,
            updated_at,
        )

    def _classify_file(
        self, ocr_text: str, candidates: list[LabelFallbackCandidate]
    ) -> LLMFallbackLabelResult:
        try:
            classification = self._llm.classify_label(ocr_text, candidates)
            label_name = classification.label_name
            confidence = float(classification.confidence)
            signals = list(classification.signals or [])
        except Exception:
            return LLMFallbackLabelResult(
                label_name=None,
                confidence=0.0,
                signals=["LLM_CLASSIFICATION_FAILED"],
            )
        if confidence < LLM_LABEL_MIN_CONFIDENCE:
            if label_name is not None:
                label_name = None
            if "BELOW_MIN_CONFIDENCE" not in signals:
                signals.append("BELOW_MIN_CONFIDENCE")
        return LLMFallbackLabelResult(
            label_name=label_name,
            confidence=confidence,
            signals=signals,
        )

    def _load_fallback_candidates(self) -> list[LabelFallbackCandidate]:
        labels = self._load_labels_json()
        labels = normalize_labels_llm(labels)
        return list_fallback_candidates(labels)

    def _load_labels_json(self) -> list[dict]:
        if not self._labels_path.exists():
            return []
        try:
            data = json.loads(self._labels_path.read_text())
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    @staticmethod
    def _default_labels_path() -> Path:
        src_root = Path(__file__).resolve().parents[2]
        return src_root.parent / "labels.json"
