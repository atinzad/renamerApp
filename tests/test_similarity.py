from app.domain.similarity import cosine_similarity, jaccard_similarity, normalize_text_to_tokens


def test_normalize_text_to_tokens_basic() -> None:
    text = "Hello, WORLD!! 42 a x"
    tokens = normalize_text_to_tokens(text)
    assert tokens == {"hello", "world", "42"}


def test_jaccard_similarity() -> None:
    assert jaccard_similarity({"a", "b"}, {"b", "c"}) == 1 / 3
    assert jaccard_similarity(set(), {"a"}) == 0.0


def test_cosine_similarity() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
