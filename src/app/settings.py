from __future__ import annotations

import os

OCR_LANG = os.getenv("OCR_LANG", "ara+eng")
EMBEDDINGS_ENABLED = os.getenv("EMBEDDINGS_ENABLED", "false").lower() == "true"
MATCH_THRESHOLD = float(os.getenv("MATCH_THRESHOLD", "0.82"))
AMBIGUITY_MARGIN = float(os.getenv("AMBIGUITY_MARGIN", "0.02"))
LEXICAL_MATCH_THRESHOLD = float(os.getenv("LEXICAL_MATCH_THRESHOLD", "0.35"))
