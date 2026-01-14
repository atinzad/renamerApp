import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.services.presets_service import PresetsService


def test_seed_if_empty_returns_false_when_not_empty(tmp_path, monkeypatch) -> None:
    storage = Mock()
    storage.count_labels.return_value = 1
    service = PresetsService(storage)

    assert service.seed_if_empty() is False


def test_seed_if_empty_loads_presets(tmp_path, monkeypatch) -> None:
    storage = Mock()
    storage.count_labels.return_value = 0
    presets_path = tmp_path / "presets.json"
    presets_path.write_text(json.dumps([{"label_id": "l1", "name": "Test"}]))

    service = PresetsService(storage)
    monkeypatch.setattr(service, "_presets_path", lambda: presets_path)

    assert service.seed_if_empty() is True
    storage.bulk_insert_label_presets.assert_called_once()


def test_export_presets_writes_file(tmp_path, monkeypatch) -> None:
    storage = Mock()
    storage.export_labels_for_presets.return_value = [{"label_id": "l1"}]
    presets_path = tmp_path / "presets.json"
    service = PresetsService(storage)
    monkeypatch.setattr(service, "_presets_path", lambda: presets_path)

    service.export_presets()

    assert presets_path.exists()
    assert json.loads(presets_path.read_text()) == [{"label_id": "l1"}]
