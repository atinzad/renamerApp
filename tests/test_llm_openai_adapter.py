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


def test_openai_adapter_extract_fields_from_image_sends_input_images(monkeypatch) -> None:
    adapter = _adapter()
    captured: dict[str, object] = {}

    def _fake_post(messages, response_format, max_tokens):
        captured["messages"] = messages
        captured["response_format"] = response_format
        captured["max_tokens"] = max_tokens
        return {"output_text": json.dumps({"civil_id": "123456789012"})}

    monkeypatch.setattr(adapter, "_post_response", _fake_post)
    monkeypatch.setattr(
        adapter, "_images_from_file_bytes", lambda file_bytes, mime_type: [b"a", b"b"]
    )

    parsed = adapter.extract_fields_from_image(
        schema={"type": "object", "properties": {"civil_id": {"type": "string"}}},
        file_bytes=b"img",
        mime_type="image/png",
        instructions="Use the signature area if available.",
    )

    assert parsed == {"civil_id": "123456789012"}
    messages = captured["messages"]
    assert isinstance(messages, list)
    assert len(messages) == 2
    user_content = messages[1]["content"]
    assert isinstance(user_content, list)
    image_blocks = [item for item in user_content if item.get("type") == "input_image"]
    assert len(image_blocks) == 2
    assert all(
        str(item.get("image_url", "")).startswith("data:image/png;base64,")
        for item in image_blocks
    )
    assert captured["response_format"] == {
        "type": "json_schema",
        "name": "extracted_fields",
        "schema": {"type": "object", "properties": {"civil_id": {"type": "string"}}},
        "strict": True,
    }


def test_openai_adapter_image_page_cap_is_applied(monkeypatch) -> None:
    adapter = OpenAILLMAdapter(
        api_key="test",
        model="mock",
        base_url="https://example.com",
        min_confidence=0.75,
        max_image_pages=2,
    )

    class _FakeImage:
        mode = "RGB"

        def convert(self, mode: str):
            _ = mode
            return self

        def save(self, buffer, format: str) -> None:
            _ = format
            buffer.write(b"x")

    monkeypatch.setattr(
        adapter,
        "_load_images",
        lambda file_bytes, mime_type: [_FakeImage(), _FakeImage(), _FakeImage()],
    )

    images = adapter._images_from_file_bytes(b"pdf", "application/pdf")
    assert len(images) == 2
