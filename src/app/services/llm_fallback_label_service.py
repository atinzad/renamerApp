from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.label_fallback import (
    LabelFallbackCandidate,
    list_fallback_candidates,
    normalize_labels_llm,
)
from app.domain.labels import NO_MATCH
from app.domain.models import FileLabelOverride, LabelAssignment
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
    ) -> None:
        self._storage = storage
        self._llm = llm

    def classify_unlabeled_files(self, job_id: str) -> None:
        candidates = self._load_fallback_candidates()
        if not candidates:
            raise RuntimeError("No fallback labels configured (labels with non-empty llm).")
        self._ensure_llm_configured()

        assignments = {item.file_id: item for item in self._storage.list_file_label_assignments(job_id)}
        overrides = {item.file_id: item for item in self._storage.list_file_label_overrides(job_id)}
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
        assignments = {item.file_id: item for item in self._storage.list_file_label_assignments(job_id)}
        overrides = {item.file_id: item for item in self._storage.list_file_label_overrides(job_id)}
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
        assignments: dict[str, LabelAssignment],
        overrides: dict[str, FileLabelOverride],
        llm_overrides: dict[str, str],
    ) -> None:
        if file_id in overrides:
            return
        if file_id in llm_overrides:
            return
        assignment = assignments.get(file_id)
        if assignment is not None and assignment.status != NO_MATCH:
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
            confidence = float(classification.confidence)
            label_name = classification.label_name
            signals = list(classification.signals or [])
        except Exception:
            return LLMFallbackLabelResult(
                label_name=None,
                confidence=0.0,
                signals=["LLM_CLASSIFICATION_FAILED"],
            )
        if label_name is None or confidence < LLM_LABEL_MIN_CONFIDENCE:
            if "BELOW_MIN_CONFIDENCE" not in signals:
                signals.append("BELOW_MIN_CONFIDENCE")
            if "ABSTAIN_NOT_ENOUGH_EVIDENCE" not in signals:
                signals.append("ABSTAIN_NOT_ENOUGH_EVIDENCE")
            return LLMFallbackLabelResult(
                label_name=None,
                confidence=confidence,
                signals=signals,
            )
        return LLMFallbackLabelResult(
            label_name=label_name,
            confidence=confidence,
            signals=signals,
        )

    def _load_fallback_candidates(self) -> list[LabelFallbackCandidate]:
        labels = self._storage.list_labels(include_inactive=False)
        label_dicts = [
            {"name": label.name, "llm": label.llm}
            for label in labels
            if label.llm and label.name
        ]
        label_dicts = normalize_labels_llm(label_dicts)
        return list_fallback_candidates(label_dicts)
