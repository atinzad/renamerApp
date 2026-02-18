from __future__ import annotations

from typing import Any

from app.adapters.embeddings_dummy import DummyEmbeddingsAdapter
from app.adapters.embeddings_openai import OpenAIEmbeddingsAdapter
from app.adapters.embeddings_sentence_transformers import SentenceTransformersEmbeddingsAdapter
from app.adapters.google_drive_adapter import GoogleDriveAdapter
from app.adapters.llm_mock import MockLLMAdapter
from app.adapters.llm_openai import OpenAILLMAdapter
from app.adapters.ocr_tesseract_adapter import TesseractOCRAdapter
from app.adapters.sqlite_storage import SQLiteStorage
from app.settings import (
    EMBEDDINGS_DEVICE,
    EMBEDDINGS_ENABLED,
    EMBEDDINGS_LOCAL_MODEL,
    EMBEDDINGS_MODEL,
    EMBEDDINGS_PROVIDER,
    LLM_EXTRACT_MAX_IMAGE_PAGES,
    LLM_LABEL_MIN_CONFIDENCE,
    LLM_PROVIDER,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    OPENAI_VISION_MODEL,
)
from app.services.jobs_service import JobsService
from app.services.label_classification_service import LabelClassificationService
from app.services.label_service import LabelService
from app.services.llm_fallback_label_service import LLMFallbackLabelService
from app.services.extraction_service import ExtractionService
from app.services.ocr_service import OCRService
from app.services.presets_service import PresetsService
from app.services.report_service import ReportService
from app.services.rename_service import RenameService
from app.services.schema_builder_service import SchemaBuilderService


def build_services(access_token: str, sqlite_path: str) -> dict[str, Any]:
    drive = GoogleDriveAdapter(access_token)
    ocr = TesseractOCRAdapter()
    embeddings = DummyEmbeddingsAdapter()
    if EMBEDDINGS_PROVIDER == "openai":
        embeddings = OpenAIEmbeddingsAdapter(
            api_key=OPENAI_API_KEY,
            model=EMBEDDINGS_MODEL,
            base_url=OPENAI_BASE_URL,
        )
    elif EMBEDDINGS_PROVIDER in {"local", "sentence-transformers", "bge-m3"}:
        embeddings = SentenceTransformersEmbeddingsAdapter(
            model_name=EMBEDDINGS_LOCAL_MODEL,
            device=EMBEDDINGS_DEVICE,
        )
    elif EMBEDDINGS_PROVIDER in {"dummy", "none"}:
        embeddings = DummyEmbeddingsAdapter()
    elif EMBEDDINGS_ENABLED:
        embeddings = DummyEmbeddingsAdapter()
    llm = MockLLMAdapter()
    if LLM_PROVIDER.lower() == "openai" and OPENAI_API_KEY:
        llm = OpenAILLMAdapter(
            api_key=OPENAI_API_KEY,
            model=OPENAI_MODEL,
            vision_model=OPENAI_VISION_MODEL,
            base_url=OPENAI_BASE_URL,
            min_confidence=LLM_LABEL_MIN_CONFIDENCE,
            max_image_pages=LLM_EXTRACT_MAX_IMAGE_PAGES,
        )
    storage = SQLiteStorage(sqlite_path)
    presets_service = PresetsService(storage)
    presets_service.seed_if_empty()
    llm_fallback_label_service = LLMFallbackLabelService(storage, llm)
    return {
        "jobs_service": JobsService(drive, storage),
        "label_classification_service": LabelClassificationService(
            embeddings, storage, llm_fallback_label_service
        ),
        "label_service": LabelService(drive, ocr, embeddings, storage),
        "llm_fallback_label_service": llm_fallback_label_service,
        "extraction_service": ExtractionService(llm, storage, drive),
        "schema_builder_service": SchemaBuilderService(storage, llm),
        "ocr_service": OCRService(drive, ocr, storage),
        "presets_service": presets_service,
        "rename_service": RenameService(drive, storage),
        "report_service": ReportService(drive, storage),
        "drive": drive,
        "embeddings": embeddings,
        "llm": llm,
        "ocr": ocr,
        "storage": storage,
    }
