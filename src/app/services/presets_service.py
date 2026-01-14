from __future__ import annotations

import json
from pathlib import Path

from app.ports.storage_port import StoragePort


class PresetsService:
    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    def seed_if_empty(self) -> bool:
        if self._storage.count_labels() != 0:
            return False
        presets_path = self._presets_path()
        if not presets_path.exists():
            return False
        try:
            data = json.loads(presets_path.read_text())
        except json.JSONDecodeError as exc:
            raise RuntimeError("Failed to load presets.json") from exc
        if not isinstance(data, list):
            raise RuntimeError("presets.json must be a list of labels")
        self._storage.bulk_insert_label_presets(data)
        return True

    def export_presets(self) -> None:
        data = self._storage.export_labels_for_presets()
        presets_path = self._presets_path()
        presets_path.write_text(json.dumps(data, indent=2, sort_keys=True))

    @staticmethod
    def _presets_path() -> Path:
        return Path(__file__).resolve().parents[4] / "presets.json"
