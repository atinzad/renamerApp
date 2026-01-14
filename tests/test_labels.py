from app.domain.labels import AMBIGUOUS, MATCHED, NO_MATCH, decide_match


def test_decide_match_no_label() -> None:
    status, rationale = decide_match(None, 0.9, None, 0.8, 0.05)
    assert status == NO_MATCH
    assert "best_label_id=None" in rationale


def test_decide_match_below_threshold() -> None:
    status, rationale = decide_match("label-1", 0.7, None, 0.8, 0.05)
    assert status == NO_MATCH
    assert "threshold" in rationale


def test_decide_match_ambiguous() -> None:
    status, rationale = decide_match("label-1", 0.85, 0.83, 0.8, 0.05)
    assert status == AMBIGUOUS
    assert "second" in rationale


def test_decide_match_matched() -> None:
    status, rationale = decide_match("label-1", 0.9, 0.7, 0.8, 0.05)
    assert status == MATCHED
    assert "best" in rationale
