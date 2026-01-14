from __future__ import annotations

from app.ports.embeddings_port import EmbeddingsPort


class DummyEmbeddingsAdapter(EmbeddingsPort):
    def embed_text(self, text: str) -> list[float]:
        raise RuntimeError("Embeddings not configured")
