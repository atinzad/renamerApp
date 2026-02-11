from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from app.domain.label_fallback import normalize_labels_llm
from app.domain.labels import NO_MATCH, decide_match
from app.domain.similarity import jaccard_similarity, normalize_text_to_tokens

_SRC_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _SRC_ROOT.parent
_JOB_FILE_WIDGET_STATE_KEY = "job_file_widget_state"
_JOB_FILE_WIDGET_PREFIXES = (
    "file_expander_",
    "preview_toggle_",
    "edit_",
    "new_label_",
    "clear_label_",
)


def _init_state() -> None:
    st.session_state.setdefault("services", None)
    st.session_state.setdefault("services_access_token", None)
    st.session_state.setdefault("services_sqlite_path", None)
    st.session_state.setdefault("job_id", None)
    st.session_state.setdefault("files", [])
    st.session_state.setdefault("preview_ops", [])
    st.session_state.setdefault("access_token", None)
    st.session_state.setdefault("access_expires_at", 0)
    st.session_state.setdefault("oauth_in_progress", False)
    st.session_state.setdefault("oauth_auth_url", None)
    st.session_state.setdefault("oauth_state", None)
    st.session_state.setdefault("manual_access_token", "")
    st.session_state.setdefault("report_preview", "")
    st.session_state.setdefault("ocr_refresh_token", "init")
    st.session_state.setdefault("ocr_ready", False)
    st.session_state.setdefault("label_selections", {})
    st.session_state.setdefault("classification_results", {})
    st.session_state.setdefault(_JOB_FILE_WIDGET_STATE_KEY, {})


def _persist_job_file_widget_state() -> None:
    snapshot: dict[str, object] = st.session_state.setdefault(
        _JOB_FILE_WIDGET_STATE_KEY, {}
    )
    for key in list(st.session_state.keys()):
        if key.startswith(_JOB_FILE_WIDGET_PREFIXES):
            snapshot[key] = st.session_state[key]


def _restore_job_file_widget_state() -> None:
    snapshot = st.session_state.get(_JOB_FILE_WIDGET_STATE_KEY, {})
    if not isinstance(snapshot, dict):
        return
    for key, value in snapshot.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            values[key] = value
    return values


def _trigger_rerun() -> None:
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def _build_suggested_names(
    files: list, selections: dict[str, str | None]
) -> dict[str, str]:
    label_to_files: dict[str, list] = {}
    for file_ref in files:
        label = selections.get(file_ref.file_id)
        if not label:
            continue
        label_to_files.setdefault(label, []).append(file_ref)

    suggestions: dict[str, str] = {}
    for label, label_files in label_to_files.items():
        total = len(label_files)
        for idx, file_ref in enumerate(label_files, start=1):
            suffix = f"_{idx:02d}" if total > 1 else ""
            extension = Path(file_ref.name).suffix
            suggestions[file_ref.file_id] = f"{label}{suffix}{extension}"
    return suggestions


def _render_preview_plan(
    container: st.delta_generator.DeltaGenerator,
    ops: list,
    notice: str | None = None,
) -> None:
    with container:
        if ops:
            st.subheader("Preview Plan")
            st.table(
                [
                    {
                        "file_id": op.file_id,
                        "old_name": op.old_name,
                        "new_name": op.new_name,
                    }
                    for op in ops
                ]
            )
        elif notice:
            st.info(notice)


def _classify_with_labels(labels: list[dict], ocr_text: str) -> tuple[str | None, float, str]:
    tokens = normalize_text_to_tokens(ocr_text)
    if not tokens or not labels:
        return None, 0.0, NO_MATCH
    label_scores: list[tuple[str, float]] = []
    for label in labels:
        name = label.get("name")
        examples = label.get("examples", [])
        if not name or not examples:
            continue
        best_score = None
        for example_text in examples:
            example_tokens = normalize_text_to_tokens(example_text)
            score = jaccard_similarity(tokens, example_tokens)
            if best_score is None or score > best_score:
                best_score = score
        if best_score is not None:
            label_scores.append((name, best_score))
    if not label_scores:
        return None, 0.0, NO_MATCH
    label_scores.sort(key=lambda item: item[1], reverse=True)
    best_label, best_score = label_scores[0]
    second_score = label_scores[1][1] if len(label_scores) > 1 else None
    status, _ = decide_match(best_label, best_score, second_score, 0.35, 0.02)
    return best_label, best_score, status


def _load_labels_from_storage(storage) -> tuple[list[dict], dict[str, str], bool]:
    labels = storage.list_labels(include_inactive=False)
    if not labels:
        fallback = _load_labels_json_readonly()
        return fallback, {}, True
    label_map = {label.name: label.label_id for label in labels}
    label_examples: dict[str, list[str]] = {label.label_id: [] for label in labels}
    for label in labels:
        examples = storage.list_label_examples(label.label_id)
        for example in examples:
            features = storage.get_label_example_features(example.example_id)
            if features and features.get("ocr_text"):
                label_examples[label.label_id].append(features["ocr_text"])
    labels_data = [
        {
            "label_id": label.label_id,
            "name": label.name,
            "llm": label.llm,
            "examples": label_examples.get(label.label_id, []),
        }
        for label in labels
    ]
    return labels_data, label_map, False


def _load_labels_json_readonly() -> list[dict]:
    path = _REPO_ROOT / "labels.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return normalize_labels_llm(data)
    return []


def _parse_extraction_payload(extraction: object | None) -> dict[str, object]:
    if not extraction:
        return {
            "fields": {},
            "confidences": {},
            "warnings": [],
            "needs_review": False,
        }
    fields_payload: dict[str, object] = {}
    confidences_payload: dict[str, object] = {}
    warnings: list[str] = []
    needs_review = False
    fields_json = _extract_object_value(extraction, "fields_json") or ""
    if fields_json:
        try:
            parsed = json.loads(fields_json)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            raw_fields = parsed.get("fields", parsed)
            if isinstance(raw_fields, dict):
                fields_payload = raw_fields
            warnings_value = parsed.get("warnings", [])
            if isinstance(warnings_value, list):
                warnings = [str(item) for item in warnings_value]
            needs_review = bool(parsed.get("needs_review", False))
    confidences_json = _extract_object_value(extraction, "confidences_json") or ""
    if confidences_json:
        try:
            parsed_confidences = json.loads(confidences_json)
        except json.JSONDecodeError:
            parsed_confidences = {}
        if isinstance(parsed_confidences, dict):
            confidences_payload = parsed_confidences
    return {
        "fields": fields_payload,
        "confidences": confidences_payload,
        "warnings": warnings,
        "needs_review": needs_review,
    }


def _extract_object_value(value: object, key: str) -> object | None:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _ocr_text_to_example(ocr_text: str) -> dict:
    example: dict[str, object] = {}
    for raw_line in ocr_text.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if key in example:
            existing = example[key]
            if isinstance(existing, list):
                existing.append(value)
            else:
                example[key] = [existing, value]
        else:
            example[key] = value
    return example
