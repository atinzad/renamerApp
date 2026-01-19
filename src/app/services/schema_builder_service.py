from __future__ import annotations

import json

from app.domain.schema_builder import (
    build_instruction_from_example,
    infer_schema_from_example,
)
from app.ports.storage_port import StoragePort


class SchemaBuilderService:
    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    def build_from_example(
        self,
        label_id: str,
        example_json: dict,
        instructions_override: str | None = None,
    ) -> None:
        schema = infer_schema_from_example(example_json)
        instructions = instructions_override
        if not instructions:
            instructions = build_instruction_from_example(schema)
        self._storage.update_label_extraction_schema(
            label_id, json.dumps(schema)
        )
        self._storage.update_label_extraction_instructions(
            label_id, instructions
        )
