import pytest

from app.adapters.embeddings_dummy import DummyEmbeddingsAdapter


def test_dummy_embeddings_raises() -> None:
    adapter = DummyEmbeddingsAdapter()
    with pytest.raises(RuntimeError, match="Embeddings not configured"):
        adapter.embed_text("hello")
