from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter

from app.domain.labels import NO_MATCH, decide_match
from app.domain.similarity import cosine_similarity, jaccard_similarity, normalize_text_to_tokens
from app.settings import AMBIGUITY_MARGIN, LEXICAL_MATCH_THRESHOLD, MATCH_THRESHOLD
from app.services.llm_fallback_label_service import LLMFallbackLabelService
from app.ports.embeddings_port import EmbeddingsPort
from app.ports.storage_port import StoragePort


class LabelClassificationService:
    def __init__(
        self,
        embeddings: EmbeddingsPort,
        storage: StoragePort,
        llm_fallback: LLMFallbackLabelService | None = None,
    ) -> None:
        self._embeddings = embeddings
        self._storage = storage
        self._llm_fallback = llm_fallback

    def classify_job_files(self, job_id: str) -> None:
        job_files = self._ordered_job_files(job_id)
        labels = self._storage.list_labels(include_inactive=False)
        label_examples = {
            label.label_id: self._storage.list_label_examples(label.label_id) for label in labels
        }

        for file_ref in job_files:
            self._classify_file(
                job_id,
                file_ref.file_id,
                labels,
                label_examples,
            )

    def classify_file(self, job_id: str, file_id: str) -> dict:
        labels = self._storage.list_labels(include_inactive=False)
        label_examples = {
            label.label_id: self._storage.list_label_examples(label.label_id) for label in labels
        }
        return self._classify_file(job_id, file_id, labels, label_examples)

    def override_file_label(self, job_id: str, file_id: str, label_id: str | None) -> None:
        self._storage.upsert_file_label_override(job_id, file_id, label_id)

    def _classify_file(
        self,
        job_id: str,
        file_id: str,
        labels: list,
        label_examples: dict[str, list],
    ) -> dict:
        started = perf_counter()
        override = self._storage.get_file_label_override(job_id, file_id)
        if override is not None:
            self._save_timing(job_id, file_id, started)
            return {
                "label_id": override,
                "score": 0.0,
                "status": "OVERRIDDEN",
                "method": None,
                "threshold": None,
                "llm_called": False,
                "llm_result": None,
            }
        ocr_result = self._storage.get_ocr_result(job_id, file_id)
        if ocr_result is None or not ocr_result.text.strip():
            self._storage.upsert_file_label_assignment(
                job_id=job_id,
                file_id=file_id,
                label_id=None,
                score=0.0,
                status=NO_MATCH,
            )
            self._save_timing(job_id, file_id, started)
            return {
                "label_id": None,
                "score": 0.0,
                "status": NO_MATCH,
                "method": None,
                "threshold": None,
                "llm_called": False,
                "llm_result": None,
            }

        ocr_text = ocr_result.text
        embedding: list[float] | None = None
        tokens: set[str] | None = None
        method = "embeddings"
        try:
            embedding = self._embeddings.embed_text(ocr_text)
        except Exception:
            embedding = None
        if not embedding:
            method = "lexical"
            tokens = normalize_text_to_tokens(ocr_text)

        label_scores: dict[str, float] = {}
        for label in labels:
            best_score = None
            for example in label_examples.get(label.label_id, []):
                features = self._storage.get_label_example_features(example.example_id)
                if features is None:
                    continue
                if method == "embeddings":
                    example_embedding = features.get("embedding")
                    if not example_embedding:
                        continue
                    score = cosine_similarity(embedding or [], example_embedding)
                else:
                    example_tokens = features.get("token_fingerprint")
                    if not example_tokens:
                        example_text = features.get("ocr_text", "")
                        example_tokens = normalize_text_to_tokens(example_text)
                    if not example_tokens:
                        continue
                    score = jaccard_similarity(tokens or set(), example_tokens)
                if best_score is None or score > best_score:
                    best_score = score
            if best_score is not None:
                label_scores[label.label_id] = best_score

        best_label_id = None
        best_score = 0.0
        second_score = None
        sorted_scores: list[tuple[str, float]] = []
        if label_scores:
            sorted_scores = sorted(
                label_scores.items(), key=lambda item: item[1], reverse=True
            )
            best_label_id, best_score = sorted_scores[0]
            if len(sorted_scores) > 1:
                second_score = sorted_scores[1][1]

        threshold = MATCH_THRESHOLD if method == "embeddings" else LEXICAL_MATCH_THRESHOLD
        status, rationale = decide_match(
            best_label_id, best_score, second_score, threshold, AMBIGUITY_MARGIN
        )
        rationale = f"{method} {rationale}"
        self._storage.upsert_file_label_assignment(
            job_id=job_id,
            file_id=file_id,
            label_id=best_label_id if status != NO_MATCH else None,
            score=best_score,
            status=status,
        )
        llm_called = False
        llm_result = None
        if status == NO_MATCH and self._llm_fallback is not None:
            try:
                self._llm_fallback.classify_file(job_id, file_id)
                llm_called = True
                llm_result = self._storage.get_llm_label_classification(job_id, file_id)
            except Exception:
                llm_called = True
                llm_result = None
        self._save_timing(job_id, file_id, started)
        return {
            "label_id": best_label_id if status != NO_MATCH else None,
            "score": best_score,
            "status": status,
            "method": method,
            "threshold": threshold,
            "llm_called": llm_called,
            "llm_result": llm_result,
            "rationale": rationale,
            "candidates": sorted_scores,
        }

    def _ordered_job_files(self, job_id: str):
        job_files = self._storage.get_job_files(job_id)
        file_rows = [
            {
                "file_ref": file_ref,
                "sort_index": file_ref.sort_index if file_ref.sort_index is not None else index,
                "name": file_ref.name,
                "file_id": file_ref.file_id,
            }
            for index, file_ref in enumerate(job_files)
        ]
        ordered_rows = sorted(
            file_rows, key=lambda row: (row["sort_index"], row["name"], row["file_id"])
        )
        return [row["file_ref"] for row in ordered_rows]

    def _save_timing(self, job_id: str, file_id: str, started: float) -> None:
        duration_ms = int((perf_counter() - started) * 1000)
        self._storage.upsert_file_timings(
            job_id=job_id,
            file_id=file_id,
            ocr_ms=None,
            classify_ms=duration_ms,
            extract_ms=None,
            updated_at_iso=datetime.now(timezone.utc).isoformat(),
        )
