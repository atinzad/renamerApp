import json

from app.adapters.llm_openai import OpenAILLMAdapter
from app.domain.label_fallback import LabelFallbackCandidate


def _adapter(min_confidence: float = 0.75) -> OpenAILLMAdapter:
    return OpenAILLMAdapter(
        api_key="test",
        model="mock",
        base_url="https://example.com",
        min_confidence=min_confidence,
    )


def test_openai_adapter_parse_failure_abstains() -> None:
    adapter = _adapter()
    result = adapter._parse_response("not-json", [])
    assert result.label_name is None
    assert result.confidence == 0.0
    assert result.signals == ["LLM_OUTPUT_PARSE_FAILED"]


def test_openai_adapter_enforces_allowlist() -> None:
    adapter = _adapter()
    candidates = [LabelFallbackCandidate(name="INVOICE", instructions="Detect invoices.")]
    payload = {"label_name": "OTHER", "confidence": 0.9, "signals": []}
    result = adapter._parse_response(json.dumps(payload), candidates)
    assert result.label_name is None
    assert "LABEL_NOT_IN_ALLOWLIST" in result.signals


def test_openai_adapter_abstains_below_min_confidence() -> None:
    adapter = _adapter(min_confidence=0.8)
    candidates = [LabelFallbackCandidate(name="INVOICE", instructions="Detect invoices.")]
    payload = {"label_name": "INVOICE", "confidence": 0.5, "signals": []}
    result = adapter._parse_response(json.dumps(payload), candidates)
    assert result.label_name is None
    assert "BELOW_MIN_CONFIDENCE" in result.signals


def test_openai_adapter_parse_fields_response_reads_fields_object() -> None:
    adapter = _adapter()
    payload = {"output_text": json.dumps({"fields": {"civil_id": "123456789012"}})}
    parsed = adapter._parse_fields_response(payload)
    assert parsed == {"civil_id": "123456789012"}
