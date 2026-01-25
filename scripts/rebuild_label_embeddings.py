from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / ".env", override=False)

from app.adapters.embeddings_openai import OpenAIEmbeddingsAdapter
from app.adapters.embeddings_sentence_transformers import SentenceTransformersEmbeddingsAdapter
from app.adapters.sqlite_storage import SQLiteStorage
from app.domain.similarity import normalize_text_to_tokens
from app.settings import (
    EMBEDDINGS_DEVICE,
    EMBEDDINGS_LOCAL_MODEL,
    EMBEDDINGS_MODEL,
    EMBEDDINGS_PROVIDER,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
)


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild embeddings for all label examples using stored OCR text."
    )
    parser.add_argument("--sqlite", default="./app.db", help="SQLite DB path.")
    args = parser.parse_args()

    storage = SQLiteStorage(args.sqlite)
    labels = storage.list_labels(include_inactive=True)
    if not labels:
        raise SystemExit("No labels found.")

    embeddings = _build_embeddings_adapter()
    processed = 0
    skipped = 0
    missing_text = 0

    for label in labels:
        examples = storage.list_label_examples(label.label_id)
        for example in examples:
            features = storage.get_label_example_features(example.example_id)
            ocr_text = features.get("ocr_text") if features else None
            if not ocr_text:
                missing_text += 1
                continue
            try:
                embedding = embeddings.embed_text(ocr_text)
            except Exception as exc:
                skipped += 1
                print(f"Skip {example.example_id}: {exc}")
                continue
            tokens = normalize_text_to_tokens(ocr_text)
            storage.save_label_example_features(
                example.example_id,
                ocr_text,
                embedding,
                tokens,
            )
            processed += 1

    print("Rebuild complete")
    print(f"  processed: {processed}")
    print(f"  skipped: {skipped}")
    print(f"  missing_ocr_text: {missing_text}")


if __name__ == "__main__":
    main()
