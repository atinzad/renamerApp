from __future__ import annotations

import os

OCR_LANG = os.getenv("OCR_LANG", "ara+eng")
EMBEDDINGS_ENABLED = os.getenv("EMBEDDINGS_ENABLED", "false").lower() == "true"
MATCH_THRESHOLD = float(os.getenv("MATCH_THRESHOLD", "0.82"))
AMBIGUITY_MARGIN = float(os.getenv("AMBIGUITY_MARGIN", "0.02"))
LEXICAL_MATCH_THRESHOLD = float(os.getenv("LEXICAL_MATCH_THRESHOLD", "0.35"))
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_LABEL_MIN_CONFIDENCE = float(os.getenv("LLM_LABEL_MIN_CONFIDENCE", "0.6"))
