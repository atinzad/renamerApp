from __future__ import annotations

import os

OCR_LANG = os.getenv("OCR_LANG", "ara+eng")
OCR_WORKERS = int(os.getenv("OCR_WORKERS", "1"))
EMBEDDINGS_ENABLED = os.getenv("EMBEDDINGS_ENABLED", "false").lower() == "true"
# Embeddings switching: openai | local | sentence-transformers | bge-m3 | dummy
EMBEDDINGS_PROVIDER = os.getenv("EMBEDDINGS_PROVIDER", "openai").lower()
# OpenAI embeddings model name (used when EMBEDDINGS_PROVIDER=openai)
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "text-embedding-3-large")
# Local sentence-transformers model name (used when EMBEDDINGS_PROVIDER=local)
EMBEDDINGS_LOCAL_MODEL = os.getenv("EMBEDDINGS_LOCAL_MODEL", "BAAI/bge-m3")
# Device for local embeddings: cpu | cuda
EMBEDDINGS_DEVICE = os.getenv("EMBEDDINGS_DEVICE", "cpu").lower()
MATCH_THRESHOLD = float(os.getenv("MATCH_THRESHOLD", "0.6"))
AMBIGUITY_MARGIN = float(os.getenv("AMBIGUITY_MARGIN", "0.02"))
LEXICAL_MATCH_THRESHOLD = float(os.getenv("LEXICAL_MATCH_THRESHOLD", "0.35"))
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_LABEL_MIN_CONFIDENCE = float(os.getenv("LLM_LABEL_MIN_CONFIDENCE", "0.6"))
