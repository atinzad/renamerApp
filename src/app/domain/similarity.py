from __future__ import annotations

import math


def normalize_text_to_tokens(text: str) -> set[str]:
    normalized_chars: list[str] = []
    for char in text.lower():
        if char.isalnum():
            normalized_chars.append(char)
        else:
            normalized_chars.append(" ")
    cleaned = "".join(normalized_chars)
    tokens = {token for token in cleaned.split() if len(token) >= 2}
    return tokens


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = a.intersection(b)
    union = a.union(b)
    if not union:
        return 0.0
    return len(intersection) / len(union)


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if len(vec_a) != len(vec_b):
        return 0.0
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
