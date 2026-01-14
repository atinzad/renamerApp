from app.ports.embeddings_port import EmbeddingsPort


class DummyEmbeddings:
    def embed_text(self, text: str) -> list[float]:
        return [1.0]


def test_embeddings_port_runtime_checkable() -> None:
    dummy = DummyEmbeddings()
    assert isinstance(dummy, EmbeddingsPort)
