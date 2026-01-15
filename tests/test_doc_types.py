import pytest

from app.domain.doc_types import DocType, clamp_confidence, parse_doc_type, signals_from_json


def test_parse_doc_type_case_insensitive() -> None:
    assert parse_doc_type("civil_id") == DocType.CIVIL_ID
    assert parse_doc_type("INVOICE") == DocType.INVOICE


def test_clamp_confidence() -> None:
    assert clamp_confidence(-0.5) == 0.0
    assert clamp_confidence(0.75) == 0.75
    assert clamp_confidence(1.5) == 1.0


def test_signals_from_json() -> None:
    assert signals_from_json(["a", "b"]) == ["a", "b"]
    assert signals_from_json('["x", "y"]') == ["x", "y"]
    with pytest.raises(ValueError):
        signals_from_json("{bad}")
