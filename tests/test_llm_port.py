from app.domain.doc_types import DocType, DocTypeClassification
from app.ports.llm_port import LLMPort


class DummyLLM:
    def classify_doc_type(self, ocr_text: str) -> DocTypeClassification:
        return DocTypeClassification(doc_type=DocType.OTHER, confidence=0.0, signals=[])


def test_llm_port_runtime_checkable() -> None:
    dummy = DummyLLM()
    assert isinstance(dummy, LLMPort)
