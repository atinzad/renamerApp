from __future__ import annotations

import json

import requests

from app.domain.label_fallback import (
    LabelFallbackCandidate,
    LabelFallbackClassification,
    clamp_confidence,
)
from app.ports.llm_port import LLMPort


class OpenAILLMAdapter(LLMPort):
    def __init__(
        self, api_key: str, model: str, base_url: str, min_confidence: float
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._min_confidence = min_confidence

    def classify_label(
        self, ocr_text: str, candidates: list[LabelFallbackCandidate]
    ) -> LabelFallbackClassification:
        if not self._api_key:
            return LabelFallbackClassification(
                label_name=None, confidence=0.0, signals=["LLM_NOT_CONFIGURED"]
            )
        if not candidates:
            return LabelFallbackClassification(
                label_name=None,
                confidence=0.0,
                signals=["ABSTAIN_NOT_ENOUGH_EVIDENCE"],
            )
        messages = self._build_messages(ocr_text, candidates)
        response = requests.post(
            f"{self._base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._model,
                "messages": messages,
                "temperature": 0.0,
                "max_tokens": 400,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        content = (
            payload.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        return self._parse_response(content, candidates)

    def extract_fields(
        self, schema: dict, ocr_text: str, instructions: str | None = None
    ) -> dict:
        if not self._api_key:
            return {}
        json_schema = self._coerce_json_schema(schema)
        instructions = instructions.strip() if instructions else ""
        instruction_line = f"{instructions}\n\n" if instructions else ""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a structured extraction assistant. "
                    f"{instruction_line}"
                    "Return JSON that matches the provided schema. "
                    "If a value is missing, return \"UNKNOWN\" for that field."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Extract fields from the OCR text using this schema.\n"
                    f"Schema:\n{json.dumps(json_schema)}\n\n"
                    "OCR text:\n"
                    f"{ocr_text}"
                ),
            },
        ]
        response = self._post_completion(
            messages,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "extracted_fields",
                    "schema": json_schema,
                    "strict": True,
                },
            },
        )
        if response is None:
            parsed = {}
        else:
            parsed = self._parse_fields_response(response)
        if not parsed:
            response = self._post_completion(
                messages,
                response_format={"type": "json_object"},
            )
            if response is None:
                return {}
            parsed = self._parse_fields_response(response)
        return parsed

    def _build_messages(
        self, ocr_text: str, candidates: list[LabelFallbackCandidate]
    ) -> list[dict[str, str]]:
        candidates_block = self._format_candidates(candidates)
        system_prompt = (
            "You are a classification assistant. "
            "You must output strict JSON with keys: label_name, confidence, signals. "
            "label_name MUST be one of the candidate names or null. "
            "If not enough evidence, label_name must be null, confidence 0.0..0.5, "
            "and signals must include ABSTAIN_NOT_ENOUGH_EVIDENCE. "
            "Return only JSON."
        )
        user_prompt = (
            "Classify the document using the OCR text and the candidate labels.\n"
            "Candidate labels:\n"
            f"{candidates_block}\n\n"
            "OCR text:\n"
            f"{ocr_text}"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _format_candidates(self, candidates: list[LabelFallbackCandidate]) -> str:
        lines: list[str] = []
        for candidate in candidates:
            name = json.dumps(candidate.name)
            instructions = json.dumps(candidate.instructions)
            lines.append(f'- NAME: {name}\n  INSTRUCTIONS: {instructions}')
        return "\n".join(lines)

    def _parse_response(
        self, content: str, candidates: list[LabelFallbackCandidate]
    ) -> LabelFallbackClassification:
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return LabelFallbackClassification(
                label_name=None, confidence=0.0, signals=["LLM_OUTPUT_PARSE_FAILED"]
            )
        if not isinstance(data, dict):
            return LabelFallbackClassification(
                label_name=None, confidence=0.0, signals=["LLM_OUTPUT_PARSE_FAILED"]
            )
        label_name = data.get("label_name")
        if label_name is not None and not isinstance(label_name, str):
            label_name = None
        if isinstance(label_name, str):
            label_name = label_name.strip() or None
        confidence = data.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        signals = data.get("signals", [])
        if not isinstance(signals, list):
            signals = []
        signals = [str(signal) for signal in signals]
        confidence = clamp_confidence(confidence)

        allowlist = {candidate.name for candidate in candidates}
        if label_name is not None and label_name not in allowlist:
            label_name = None
            signals.append("LABEL_NOT_IN_ALLOWLIST")
        if confidence < self._min_confidence:
            label_name = None
            signals.append("BELOW_MIN_CONFIDENCE")
        signals = self._dedupe_signals(signals)
        return LabelFallbackClassification(
            label_name=label_name, confidence=confidence, signals=signals
        )

    @staticmethod
    def _dedupe_signals(signals: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for signal in signals:
            if signal in seen:
                continue
            seen.add(signal)
            deduped.append(signal)
        return deduped

    @staticmethod
    def _coerce_json_schema(schema: dict) -> dict:
        if isinstance(schema, dict) and schema.get("type") and schema.get("properties"):
            return schema
        properties = {}
        if isinstance(schema, dict):
            for key in schema.keys():
                properties[str(key)] = {"type": "string"}
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties.keys()),
            "additionalProperties": False,
        }

    def _post_completion(
        self, messages: list[dict[str, str]], response_format: dict
    ) -> dict | None:
        try:
            response = requests.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": messages,
                    "response_format": response_format,
                    "temperature": 0.0,
                    "max_tokens": 800,
                },
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException:
            return None
        return response.json()

    @staticmethod
    def _parse_fields_response(payload: dict) -> dict:
        content = (
            payload.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return {}
        if isinstance(data, dict):
            fields = data.get("fields")
            if isinstance(fields, dict):
                return fields
            return data
        return {}
