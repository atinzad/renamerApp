from __future__ import annotations

from app.ports.embeddings_port import EmbeddingsPort


class SentenceTransformersEmbeddingsAdapter(EmbeddingsPort):
    def __init__(self, model_name: str, device: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # pragma: no cover - import-time error handling
            raise RuntimeError(
                "sentence-transformers not installed. Install it to use local embeddings."
            ) from exc
        self._model = SentenceTransformer(model_name, device=device)

    def embed_text(self, text: str) -> list[float]:
        embedding = self._model.encode(text, normalize_embeddings=True)
        return embedding.tolist()
