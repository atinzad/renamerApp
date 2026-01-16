from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LabelFallbackCandidate:
    name: str
    instructions: str


@dataclass
class LabelFallbackClassification:
    label_name: str | None
    confidence: float
    signals: list[str]


def clamp_confidence(confidence: float) -> float:
    """Clamp a confidence value to the 0..1 range."""

    if confidence < 0.0:
        return 0.0
    if confidence > 1.0:
        return 1.0
    return confidence


def normalize_label_llm(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def normalize_labels_llm(labels: list[dict]) -> list[dict]:
    for label in labels:
        label["llm"] = normalize_label_llm(label.get("llm"))
    return labels


def list_fallback_candidates(labels: list[dict]) -> list[LabelFallbackCandidate]:
    candidates: list[LabelFallbackCandidate] = []
    for label in labels:
        name = str(label.get("name", "")).strip()
        llm_instructions = normalize_label_llm(label.get("llm"))
        if name and llm_instructions:
            candidates.append(
                LabelFallbackCandidate(name=name, instructions=llm_instructions)
            )
    return candidates
