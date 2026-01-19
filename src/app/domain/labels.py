from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

MATCHED = "MATCHED"
AMBIGUOUS = "AMBIGUOUS"
NO_MATCH = "NO_MATCH"


@dataclass
class Label:
    label_id: str
    name: str
    is_active: bool
    created_at: datetime
    extraction_schema_json: str
    naming_template: str
    llm: str
    extraction_instructions: str = ""


@dataclass
class LabelExample:
    example_id: str
    label_id: str
    file_id: str
    filename: str
    created_at: datetime


@dataclass
class LabelMatch:
    label_id: str | None
    score: float
    rationale: str
    status: str


def decide_match(
    best_label_id: str | None,
    best: float,
    second: float | None,
    match_threshold: float,
    ambiguity_margin: float,
) -> tuple[str, str]:
    if best_label_id is None:
        return NO_MATCH, "best_label_id=None"
    if best < match_threshold:
        rationale = f"best={best:.4f} threshold={match_threshold:.4f}"
        return NO_MATCH, rationale
    if (
        second is not None
        and second >= match_threshold
        and (best - second) < ambiguity_margin
    ):
        rationale = (
            f"best={best:.4f} second={second:.4f} "
            f"threshold={match_threshold:.4f} margin={ambiguity_margin:.4f}"
        )
        return AMBIGUOUS, rationale
    rationale = f"best={best:.4f} threshold={match_threshold:.4f}"
    return MATCHED, rationale
