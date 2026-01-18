from app.domain.label_fallback import LabelFallbackCandidate, LabelFallbackClassification
from app.ports.llm_port import LLMPort


class DummyLLM:
    def classify_label(
        self, ocr_text: str, candidates: list[LabelFallbackCandidate]
    ) -> LabelFallbackClassification:
        return LabelFallbackClassification(
            label_name=None, confidence=0.0, signals=["LLM_NOT_CONFIGURED"]
        )

    def extract_fields(self, schema: dict, ocr_text: str) -> dict:
        return {}


def test_llm_port_runtime_checkable() -> None:
    dummy = DummyLLM()
    assert isinstance(dummy, LLMPort)
