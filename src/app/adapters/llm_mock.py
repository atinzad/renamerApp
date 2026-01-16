from __future__ import annotations

from app.domain.label_fallback import LabelFallbackCandidate, LabelFallbackClassification
from app.ports.llm_port import LLMPort


class MockLLMAdapter(LLMPort):
    def classify_label(
        self, ocr_text: str, candidates: list[LabelFallbackCandidate]
    ) -> LabelFallbackClassification:
        return LabelFallbackClassification(
            label_name=None, confidence=0.0, signals=["LLM_NOT_CONFIGURED"]
        )
