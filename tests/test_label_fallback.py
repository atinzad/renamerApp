from app.domain.label_fallback import (
    LabelFallbackCandidate,
    clamp_confidence,
    list_fallback_candidates,
    normalize_labels_llm,
)


def test_normalize_labels_llm_defaults_missing_llm() -> None:
    labels = [{"name": "INVOICE"}, {"name": "ID", "llm": "  "}]
    normalized = normalize_labels_llm(labels)
    assert normalized[0]["llm"] == ""
    assert normalized[1]["llm"] == ""


def test_list_fallback_candidates_filters_on_llm() -> None:
    labels = [
        {"name": "INVOICE", "llm": "Find invoices."},
        {"name": "ID", "llm": ""},
        {"name": "  ", "llm": "Missing name."},
    ]
    candidates = list_fallback_candidates(labels)
    assert candidates == [
        LabelFallbackCandidate(name="INVOICE", instructions="Find invoices.")
    ]


def test_clamp_confidence_bounds() -> None:
    assert clamp_confidence(-0.5) == 0.0
    assert clamp_confidence(1.2) == 1.0
    assert clamp_confidence(0.5) == 0.5
