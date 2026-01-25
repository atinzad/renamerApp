from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / ".env", override=False)

from app.adapters.embeddings_openai import OpenAIEmbeddingsAdapter
from app.adapters.embeddings_sentence_transformers import SentenceTransformersEmbeddingsAdapter
from app.adapters.llm_mock import MockLLMAdapter
from app.adapters.llm_openai import OpenAILLMAdapter
from app.adapters.sqlite_storage import SQLiteStorage
from app.domain.label_fallback import LabelFallbackCandidate
from app.domain.labels import NO_MATCH, decide_match
from app.domain.similarity import cosine_similarity, jaccard_similarity, normalize_text_to_tokens
from app.settings import (
    AMBIGUITY_MARGIN,
    EMBEDDINGS_DEVICE,
    EMBEDDINGS_LOCAL_MODEL,
    EMBEDDINGS_MODEL,
    EMBEDDINGS_PROVIDER,
    LEXICAL_MATCH_THRESHOLD,
    LLM_LABEL_MIN_CONFIDENCE,
    LLM_PROVIDER,
    MATCH_THRESHOLD,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
)


@dataclass(frozen=True)
class ScoredLabel:
    label_id: str
    label_name: str
    best_score: float
    second_score: float | None
    status: str


def _build_embeddings_adapter():
    if EMBEDDINGS_PROVIDER == "openai":
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI embeddings.")
        return OpenAIEmbeddingsAdapter(
            api_key=OPENAI_API_KEY,
            model=EMBEDDINGS_MODEL,
            base_url=OPENAI_BASE_URL,
        )
    if EMBEDDINGS_PROVIDER in {"local", "sentence-transformers", "bge-m3"}:
        return SentenceTransformersEmbeddingsAdapter(
            model_name=EMBEDDINGS_LOCAL_MODEL,
            device=EMBEDDINGS_DEVICE,
        )
    raise RuntimeError(
        "Embeddings provider not configured. Set EMBEDDINGS_PROVIDER to openai or local."
    )


def _build_llm_adapter():
    if LLM_PROVIDER.lower() == "openai" and OPENAI_API_KEY:
        return OpenAILLMAdapter(
            api_key=OPENAI_API_KEY,
            model=OPENAI_MODEL,
            base_url=OPENAI_BASE_URL,
            min_confidence=LLM_LABEL_MIN_CONFIDENCE,
        )
    return MockLLMAdapter()


def _rank_scores(label_scores: dict[str, float], label_name_by_id: dict[str, str]) -> ScoredLabel:
    if not label_scores:
        return ScoredLabel("", "", 0.0, None, NO_MATCH)
    sorted_scores = sorted(label_scores.items(), key=lambda item: item[1], reverse=True)
    best_label_id, best_score = sorted_scores[0]
    second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else None
    status, _ = decide_match(
        best_label_id, best_score, second_score, MATCH_THRESHOLD, AMBIGUITY_MARGIN
    )
    return ScoredLabel(
        best_label_id,
        label_name_by_id.get(best_label_id, ""),
        best_score,
        second_score,
        status,
    )


def _rank_scores_lexical(
    label_scores: dict[str, float], label_name_by_id: dict[str, str]
) -> ScoredLabel:
    if not label_scores:
        return ScoredLabel("", "", 0.0, None, NO_MATCH)
    sorted_scores = sorted(label_scores.items(), key=lambda item: item[1], reverse=True)
    best_label_id, best_score = sorted_scores[0]
    second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else None
    status, _ = decide_match(
        best_label_id,
        best_score,
        second_score,
        LEXICAL_MATCH_THRESHOLD,
        AMBIGUITY_MARGIN,
    )
    return ScoredLabel(
        best_label_id,
        label_name_by_id.get(best_label_id, ""),
        best_score,
        second_score,
        status,
    )


def _format_score(value: float | None) -> str:
    if value is None or math.isnan(value):
        return "n/a"
    return f"{value * 100:.2f}%"


def _summarize_scores(title: str, scored: ScoredLabel) -> None:
    print(f"\n{title}")
    if not scored.label_id:
        print("  result: NO_MATCH")
        return
    print(f"  best label: {scored.label_name} ({scored.label_id})")
    print(f"  best score: {_format_score(scored.best_score)}")
    if scored.second_score is not None:
        print(f"  second score: {_format_score(scored.second_score)}")
    print(f"  status: {scored.status}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr", default="ocr_text.txt", help="Path to OCR text file.")
    parser.add_argument("--sqlite", default="./app.db", help="SQLite DB path.")
    args = parser.parse_args()

    ocr_text = Path(args.ocr).read_text(encoding="utf-8")
    if not ocr_text.strip():
        raise SystemExit("OCR text file is empty.")

    storage = SQLiteStorage(args.sqlite)
    labels = storage.list_labels(include_inactive=False)
    if not labels:
        raise SystemExit("No labels found in SQLite.")
    label_name_by_id = {label.label_id: label.name for label in labels}

    examples_by_label: dict[str, list[dict]] = {}
    for label in labels:
        examples = storage.list_label_examples(label.label_id)
        example_rows: list[dict] = []
        for example in examples:
            features = storage.get_label_example_features(example.example_id)
            example_rows.append(
                {
                    "example_id": example.example_id,
                    "file_id": example.file_id,
                    "ocr_text": features.get("ocr_text") if features else None,
                    "tokens": features.get("token_fingerprint") if features else None,
                    "embedding": features.get("embedding") if features else None,
                }
            )
        examples_by_label[label.label_id] = example_rows

    token_set = normalize_text_to_tokens(ocr_text)
    print("OCR stats")
    print(f"  chars: {len(ocr_text)}")
    print(f"  tokens: {len(token_set)}")

    print("\nLabel coverage")
    for label in labels:
        examples = examples_by_label.get(label.label_id, [])
        print(f"  - {label.name}: {len(examples)} example(s)")

    # Embeddings classification
    embeddings_scores: dict[str, float] = {}
    try:
        embeddings_adapter = _build_embeddings_adapter()
        ocr_embedding = embeddings_adapter.embed_text(ocr_text)
        for label in labels:
            best_score = None
            for example in examples_by_label.get(label.label_id, []):
                example_embedding = example.get("embedding")
                if not example_embedding and example.get("ocr_text"):
                    example_embedding = embeddings_adapter.embed_text(example["ocr_text"])
                if not example_embedding:
                    continue
                score = cosine_similarity(ocr_embedding, example_embedding)
                if best_score is None or score > best_score:
                    best_score = score
            if best_score is not None:
                embeddings_scores[label.label_id] = best_score
        _summarize_scores("Embeddings classification", _rank_scores(embeddings_scores, label_name_by_id))
    except Exception as exc:
        print("\nEmbeddings classification")
        print(f"  error: {exc}")

    # Lexical Jaccard classification
    lexical_scores: dict[str, float] = {}
    if token_set:
        for label in labels:
            best_score = None
            for example in examples_by_label.get(label.label_id, []):
                example_tokens = example.get("tokens")
                if not example_tokens and example.get("ocr_text"):
                    example_tokens = normalize_text_to_tokens(example["ocr_text"])
                if not example_tokens:
                    continue
                score = jaccard_similarity(token_set, example_tokens)
                if best_score is None or score > best_score:
                    best_score = score
            if best_score is not None:
                lexical_scores[label.label_id] = best_score
    _summarize_scores("Lexical (Jaccard) classification", _rank_scores_lexical(lexical_scores, label_name_by_id))

    # LLM fallback classification
    llm = _build_llm_adapter()
    candidates = [
        LabelFallbackCandidate(name=label.name, instructions=label.llm or "")
        for label in labels
        if label.llm
    ]
    if not candidates:
        print("\nLLM fallback classification")
        print("  error: No labels have LLM instructions (llm field is empty).")
        return
    best_label = None
    best_confidence = 0.0
    best_signals: list[str] = []
    print("\nLLM fallback classification (per-label)")
    for candidate in candidates:
        result = llm.classify_label(ocr_text, [candidate])
        print(f"  - {candidate.name}: {result.confidence:.3f} ({result.label_name})")
        if result.label_name and result.confidence > best_confidence:
            best_confidence = float(result.confidence)
            best_label = result.label_name
            best_signals = list(result.signals or [])
    if best_label and best_confidence >= LLM_LABEL_MIN_CONFIDENCE:
        print(f"  best: {best_label} ({best_confidence:.3f})")
        if best_signals:
            print(f"  signals: {best_signals}")
    else:
        print("  best: ABSTAIN")


if __name__ == "__main__":
    main()
