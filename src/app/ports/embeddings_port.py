from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingsPort(Protocol):
    def embed_text(self, text: str) -> list[float]:
        """Return a vector embedding for the given text."""
