from __future__ import annotations

import requests

from app.ports.embeddings_port import EmbeddingsPort


class OpenAIEmbeddingsAdapter(EmbeddingsPort):
    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")

    def embed_text(self, text: str) -> list[float]:
        if not self._api_key:
            raise RuntimeError("OpenAI embeddings not configured")
        response = requests.post(
            f"{self._base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._model,
                "input": text,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", [])
        if not data:
            raise RuntimeError("OpenAI embeddings returned no data")
        embedding = data[0].get("embedding")
        if not isinstance(embedding, list):
            raise RuntimeError("OpenAI embeddings response missing embedding list")
        return embedding
