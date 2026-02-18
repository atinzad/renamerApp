from __future__ import annotations

import base64
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

_SRC_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _SRC_ROOT.parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

# Load repo .env so settings/env-based features work without manual exports.
load_dotenv(_REPO_ROOT / ".env", override=False)

from app.container import build_services
from app.domain.label_fallback import list_fallback_candidates
from app.domain.labels import AMBIGUOUS, MATCHED, NO_MATCH
from app.domain.models import LLMLabelClassification
from app.domain.similarity import normalize_text_to_tokens
from app.ui_streamlit.helpers import (
    _build_suggested_names,
    _classify_with_labels,
    _init_state,
    _load_env_file,
    _load_labels_from_storage,
    _load_labels_json_readonly,
    _ocr_text_to_example,
    _parse_extraction_payload,
    _persist_job_file_widget_state,
    _render_preview_plan,
    _restore_job_file_widget_state,
    _trigger_rerun,
)
from app.ui_streamlit.auth import ensure_access_token, render_auth_controls
from app.ui_streamlit.labels_view import render_labels_view

_PREVIEW_MAX_BYTES = 10 * 1024 * 1024


def _get_services(access_token: str, sqlite_path: str):
    if (
        st.session_state["services"] is None
        or st.session_state.get("services_access_token") != access_token
        or st.session_state.get("services_sqlite_path") != sqlite_path
    ):
        st.session_state["services"] = build_services(access_token, sqlite_path)
        st.session_state["services_access_token"] = access_token
        st.session_state["services_sqlite_path"] = sqlite_path
    return st.session_state["services"]


def _extract_folder_id(value: str) -> str:
    if not value:
        return ""
    trimmed = value.strip()
    parsed = urlparse(trimmed)
    if parsed.scheme and parsed.netloc:
        params = parse_qs(parsed.query)
        if "id" in params and params["id"]:
            return params["id"][0]
        parts = parsed.path.split("/")
        if "folders" in parts:
            idx = parts.index("folders")
            if idx + 1 < len(parts):
                return parts[idx + 1]
    return trimmed


def main() -> None:
    st.title("Google Drive Image Renamer")
    _init_state()

    view = st.sidebar.radio("View", ["Job", "Labels"], index=0)

    env_values = _load_env_file(_REPO_ROOT / ".env")
    env_folder_id = env_values.get("FOLDER_ID", "")
    sqlite_path = st.text_input("SQLite Path", value="./app.db")

    if view == "Labels":
        _persist_job_file_widget_state()
        render_labels_view("", sqlite_path, _get_services)
        return

    _restore_job_file_widget_state()

    auth_inputs = render_auth_controls(env_values)
    client_id = auth_inputs.client_id
    client_secret = auth_inputs.client_secret
    access_token = auth_inputs.access_token

    folder_id = st.text_input(
        "Folder ID or URL",
        value=env_folder_id,
        help="Paste a Drive folder ID or the full folder URL.",
    )

    cols = st.columns(4)
    list_clicked = cols[0].button("List Files")
    preview_clicked = cols[1].button("Preview")
    apply_clicked = cols[2].button("Apply Rename")
    undo_clicked = cols[3].button("Undo Rename")

    if list_clicked:
        try:
            token = ensure_access_token(access_token, client_id, client_secret)
            services = _get_services(token, sqlite_path)
            extracted_folder_id = _extract_folder_id(folder_id)
            if not extracted_folder_id:
                raise RuntimeError("Folder ID is required.")
            job = services["jobs_service"].create_job(extracted_folder_id)
            files = services["jobs_service"].list_files(job.job_id)
            storage = services["storage"]
            ocr_ready_count = 0
            classified_count = 0
            extracted_count = 0
            for file_ref in files:
                ocr_result = storage.get_ocr_result(job.job_id, file_ref.file_id)
                if ocr_result and ocr_result.text.strip():
                    ocr_ready_count += 1
                if storage.get_file_label_assignment(job.job_id, file_ref.file_id):
                    classified_count += 1
                if storage.get_extraction(job.job_id, file_ref.file_id):
                    extracted_count += 1
            st.session_state["job_id"] = job.job_id
            st.session_state["files"] = files
            st.session_state["preview_ops"] = []
            st.session_state["preview_notice"] = ""
            st.session_state["classification_results"] = {}
            st.session_state["label_selections"] = {}
            st.session_state["ocr_ready"] = bool(files) and ocr_ready_count == len(files)
            st.info(
                f"Listed {len(files)} files from Drive. Job ID: {job.job_id}. "
                f"DB reuse: OCR {ocr_ready_count}/{len(files)}, "
                f"classification {classified_count}/{len(files)}, "
                f"extraction {extracted_count}/{len(files)}."
            )
        except Exception as exc:
            st.error(f"List files failed: {exc}")

    job_id = st.session_state.get("job_id")
    preview_container = st.container()
    if job_id:
        st.subheader("Job")
        st.write(f"Job ID: {job_id}")
        try:
            token = ensure_access_token(access_token, client_id, client_secret)
            services = _get_services(token, sqlite_path)
            summary = services["report_service"].get_final_report_summary(job_id)
            st.caption(
                "Summary — "
                f"Renamed: {summary['renamed']}, "
                f"Skipped: {summary['skipped']}, "
                f"Needs review: {summary['needs_review']}"
            )
        except Exception:
            pass

        report_cols = st.columns(5)
        run_ocr_clicked = report_cols[0].button(
            "Run OCR",
            disabled=job_id is None,
        )
        report_cols[0].caption("Required before classification.")
        classify_clicked = report_cols[1].button("Classify files")
        report_cols[1].caption(
            "Embedding + lexical, with LLM fallback on no-match (uses OCR text)."
        )
        extract_clicked = report_cols[2].button("Extract fields")
        report_cols[2].caption("LLM-powered field extraction from source image/PDF (not OCR text).")
        preview_report_clicked = report_cols[3].button("Preview Final Report")
        write_report_clicked = report_cols[4].button(
            "Write Final Report",
            disabled=job_id is None,
        )
        if run_ocr_clicked:
            try:
                token = ensure_access_token(access_token, client_id, client_secret)
                services = _get_services(token, sqlite_path)
                with st.spinner("Running OCR..."):
                    services["ocr_service"].run_ocr(job_id)
                st.session_state["files"] = services["jobs_service"].list_files(job_id)
                st.session_state["ocr_refresh_token"] = str(uuid4())
                st.session_state["ocr_ready"] = True
                st.success("OCR completed.")
            except Exception as exc:
                st.error(f"OCR failed: {exc}")
        if preview_report_clicked:
            try:
                token = ensure_access_token(access_token, client_id, client_secret)
                services = _get_services(token, sqlite_path)
                report_text = services["report_service"].preview_report(job_id)
                st.session_state["report_preview"] = report_text
                st.success("Final report preview generated.")
            except Exception as exc:
                st.error(f"Report preview failed: {exc}")

        if extract_clicked:
            try:
                token = ensure_access_token(access_token, client_id, client_secret)
                services = _get_services(token, sqlite_path)
                with st.spinner("Extracting fields..."):
                    services["extraction_service"].extract_fields_for_job(job_id)
                st.success("Extraction completed.")
                _trigger_rerun()
            except Exception as exc:
                st.error(f"Extraction failed: {exc}")

        st.text_area(
            "Final Report Preview",
            value=st.session_state.get("report_preview", ""),
            height=300,
        )

        if write_report_clicked:
            try:
                token = ensure_access_token(access_token, client_id, client_secret)
                services = _get_services(token, sqlite_path)
                report_file_id = services["report_service"].write_report(job_id)
                st.success(f"Final report uploaded. File ID: {report_file_id}")
            except Exception as exc:
                st.error(f"Report upload failed: {exc}")
        if classify_clicked:
            if not st.session_state.get("ocr_ready"):
                st.error("Run OCR first.")
            else:
                try:
                    token = ensure_access_token(access_token, client_id, client_secret)
                    services = _get_services(token, sqlite_path)
                    results: dict[str, dict] = {}
                    try:
                        labels_data, _, _ = _load_labels_from_storage(services["storage"])
                    except Exception:
                        labels_data = _load_labels_json_readonly()
                    has_labels = bool(labels_data)
                    has_examples = any(label.get("examples") for label in labels_data)
                    label_id_map = {label.get("label_id"): label.get("name") for label in labels_data}
                    missing_ocr_count = 0
                    tokenless_count = 0
                    for file_ref in st.session_state.get("files", []):
                        ocr_result = services["storage"].get_ocr_result(
                            job_id, file_ref.file_id
                        )
                        if ocr_result is None or not ocr_result.text.strip():
                            missing_ocr_count += 1
                            results[file_ref.file_id] = {
                                "label": None,
                                "score": 0.0,
                                "status": NO_MATCH,
                                "method": None,
                                "threshold": None,
                                "llm_called": False,
                                "llm_result": None,
                            }
                            continue
                        if not normalize_text_to_tokens(ocr_result.text):
                            tokenless_count += 1
                        details = services["label_classification_service"].classify_file(
                            job_id, file_ref.file_id
                        )
                        label_name = label_id_map.get(details.get("label_id"))
                        results[file_ref.file_id] = {
                            "label": label_name,
                            "score": details.get("score", 0.0),
                            "status": details.get("status", NO_MATCH),
                            "method": details.get("method"),
                            "threshold": details.get("threshold"),
                            "llm_called": details.get("llm_called", False),
                            "llm_result": details.get("llm_result"),
                            "candidates": details.get("candidates", []),
                        }
                    st.session_state["classification_results"] = results
                    current_selections = dict(st.session_state.get("label_selections", {}))
                    for file_id, result in results.items():
                        if result["status"] == MATCHED and result["label"]:
                            current_selections[file_id] = result["label"]
                        else:
                            current_selections[file_id] = None
                            rename_key = f"edit_{file_id}"
                            st.session_state[rename_key] = ""
                    st.session_state["label_selections"] = current_selections
                    suggestions = _build_suggested_names(
                        st.session_state.get("files", []), current_selections
                    )
                    for file_id, suggested in suggestions.items():
                        rename_key = f"edit_{file_id}"
                        if current_selections.get(file_id):
                            st.session_state[rename_key] = suggested
                    if not has_labels:
                        st.warning(
                            "No labels found. Create labels and add examples in the Labels view "
                            "to enable rule-based classification."
                        )
                    elif not has_examples:
                        st.warning(
                            "Labels exist but no examples were found. Add OCR examples to labels "
                            "so similarity scores are meaningful."
                        )
                    if missing_ocr_count:
                        st.warning(
                            f"{missing_ocr_count} file(s) have no OCR text. Run OCR first to "
                            "enable classification."
                        )
                    if tokenless_count:
                        st.warning(
                            f"{tokenless_count} file(s) produced no usable tokens. This can happen "
                            "if OCR text is empty or only contains punctuation. Arabic text is "
                            "now supported, so re-run OCR if needed."
                        )
                    st.success("Classification completed.")
                except Exception as exc:
                    st.error(f"Classification failed: {exc}")

    files = st.session_state.get("files", [])
    edits: dict[str, str] = {}
    label_selections = st.session_state.get("label_selections", {})
    labels_data: list[dict] = []
    label_id_map: dict[str, str] = {}
    using_json_fallback = False
    if job_id:
        try:
            token = ensure_access_token(access_token, client_id, client_secret)
            services = _get_services(token, sqlite_path)
            labels_data, label_id_map, using_json_fallback = _load_labels_from_storage(
                services["storage"]
            )
        except Exception:
            labels_data = _load_labels_json_readonly()
            using_json_fallback = True
    label_names = [label.get("name") for label in labels_data if label.get("name")]
    label_name_by_id = {
        label_id: name for name, label_id in label_id_map.items() if name and label_id
    }
    fallback_candidates = list_fallback_candidates(labels_data)
    fallback_candidate_names = [candidate.name for candidate in fallback_candidates]
    classification_results = st.session_state.get("classification_results", {})
    llm_classifications: dict[str, LLMLabelClassification] = {}
    llm_overrides: dict[str, str] = {}
    storage = None
    if job_id:
        try:
            token = ensure_access_token(access_token, client_id, client_secret)
            services = _get_services(token, sqlite_path)
            storage = services["storage"]
            llm_classifications = services["storage"].list_llm_label_classifications(job_id)
            llm_overrides = services["storage"].list_llm_label_overrides(job_id)
        except Exception as exc:
            st.error(f"LLM fallback lookup failed: {exc}")
    if files:
        st.subheader("Files")
        if using_json_fallback and labels_data:
            st.info("Labels loaded from labels.json. Run the migration to use SQLite.")
        current_selections = dict(label_selections)
        ocr_status: dict[str, dict[str, bool]] = {}
        file_timings: dict[str, dict[str, int | None]] = {}
        stored_classification_labels: dict[str, str] = {}
        stored_assignments: dict[str, object] = {}
        extraction_done: dict[str, bool] = {}
        if storage and job_id:
            for file_ref in files:
                ocr_result = storage.get_ocr_result(job_id, file_ref.file_id)
                has_ocr = bool(ocr_result and ocr_result.text.strip())
                has_tokens = bool(
                    normalize_text_to_tokens(ocr_result.text) if has_ocr else False
                )
                ocr_status[file_ref.file_id] = {
                    "has_ocr": has_ocr,
                    "has_tokens": has_tokens,
                }
                try:
                    timings = storage.get_file_timings(job_id, file_ref.file_id)
                except Exception:
                    timings = None
                file_timings[file_ref.file_id] = {
                    "ocr_ms": getattr(timings, "ocr_ms", None) if timings else None,
                    "classify_ms": getattr(timings, "classify_ms", None) if timings else None,
                    "extract_ms": getattr(timings, "extract_ms", None) if timings else None,
                }
                try:
                    assignment = storage.get_file_label_assignment(job_id, file_ref.file_id)
                except Exception:
                    assignment = None
                if assignment:
                    stored_assignments[file_ref.file_id] = assignment
                    if assignment.label_id:
                        stored_classification_labels[file_ref.file_id] = label_name_by_id.get(
                            assignment.label_id, assignment.label_id
                        )
                try:
                    extraction_done[file_ref.file_id] = bool(
                        storage.get_extraction(job_id, file_ref.file_id)
                    )
                except Exception:
                    extraction_done[file_ref.file_id] = False
        for file_ref in files:
            badges: list[str] = []
            progress: list[str] = []
            status = ocr_status.get(file_ref.file_id)
            if status:
                if status.get("has_ocr"):
                    progress.append("OCR done")
                else:
                    badges.append("NO OCR")
                if status.get("has_ocr") and not status.get("has_tokens"):
                    badges.append("NO TOKENS")
            classification_label = current_selections.get(file_ref.file_id)
            if not classification_label:
                classification_label = stored_classification_labels.get(file_ref.file_id)
            if not classification_label:
                result = classification_results.get(file_ref.file_id)
                if result and result.get("label"):
                    classification_label = str(result["label"])
            if classification_label:
                progress.append(f"Classification {classification_label}")
            if extraction_done.get(file_ref.file_id):
                progress.append("Extraction done")
            status_parts = progress + badges
            badge_text = f" [{' | '.join(status_parts)}]" if status_parts else ""
            expander_key = f"file_expander_{file_ref.file_id}"
            st.markdown(f"**{file_ref.name}**{badge_text}")
            st.caption(f"{file_ref.file_id} • {file_ref.mime_type}")
            expanded = st.toggle(
                "Show details",
                value=st.session_state.get(expander_key, False),
                key=expander_key,
            )
            if expanded:
                timing = file_timings.get(file_ref.file_id, {})
                timing_text = (
                    f"OCR: {timing.get('ocr_ms') if timing.get('ocr_ms') is not None else '—'} ms | "
                    f"Classification: {timing.get('classify_ms') if timing.get('classify_ms') is not None else '—'} ms | "
                    f"Extraction: {timing.get('extract_ms') if timing.get('extract_ms') is not None else '—'} ms"
                )
                st.caption(timing_text)
                selection_key = f"label_select_{file_ref.file_id}"
                label_options = ["(Clear)"] + label_names
                current_label = current_selections.get(file_ref.file_id)
                selected_index = (
                    label_options.index(current_label) if current_label in label_options else 0
                )
                choice = st.selectbox(
                    "Classify",
                    label_options,
                    index=selected_index,
                    key=selection_key,
                )
                selected_label = None if choice == "(Clear)" else choice
                previous_label = current_selections.get(file_ref.file_id)
                current_selections[file_ref.file_id] = selected_label
                if job_id and selected_label != previous_label:
                    try:
                        token = ensure_access_token(access_token, client_id, client_secret)
                        services = _get_services(token, sqlite_path)
                        label_id = label_id_map.get(selected_label) if selected_label else None
                        services["label_classification_service"].override_file_label(
                            job_id, file_ref.file_id, label_id
                        )
                    except Exception as exc:
                        st.error(f"Override update failed: {exc}")
                if selected_label and job_id:
                    if st.button(
                        "Add as label example",
                        key=f"add_example_{file_ref.file_id}",
                    ):
                        try:
                            token = ensure_access_token(access_token, client_id, client_secret)
                            services = _get_services(token, sqlite_path)
                            ocr_result = services["storage"].get_ocr_result(
                                job_id, file_ref.file_id
                            )
                            if ocr_result is None or not ocr_result.text.strip():
                                st.error("Run OCR first to capture this example.")
                            else:
                                label_id = label_id_map.get(selected_label)
                                if not label_id:
                                    st.error("Label not found.")
                                else:
                                    examples = services["storage"].list_label_examples(label_id)
                                    if any(
                                        example.file_id == file_ref.file_id
                                        for example in examples
                                    ):
                                        st.info("This file is already an example for the label.")
                                    else:
                                        services["label_service"].attach_example(
                                            label_id, file_ref.file_id
                                        )
                                        services["label_service"].process_examples(
                                            label_id, job_id=job_id
                                        )
                                        st.success("Example added to label.")
                                        _trigger_rerun()
                        except Exception as exc:
                            st.error(f"Add example failed: {exc}")

                with st.expander("Create new label", expanded=False):
                    new_label_key = f"new_label_{file_ref.file_id}"
                    clear_key = f"clear_label_{file_ref.file_id}"
                    if st.session_state.get(clear_key):
                        st.session_state[new_label_key] = ""
                        st.session_state[clear_key] = False
                    new_label = st.text_input(
                        "Label name",
                        value=st.session_state.get(new_label_key, ""),
                        key=new_label_key,
                    )
                    if st.button("Create Label", key=f"create_label_{file_ref.file_id}"):
                        if not new_label.strip():
                            st.error("Label name is required.")
                        elif not job_id:
                            st.error("List files and run OCR before creating labels.")
                        else:
                            try:
                                token = ensure_access_token(
                                    access_token, client_id, client_secret
                                )
                                services = _get_services(token, sqlite_path)
                                ocr_result = services["storage"].get_ocr_result(
                                    job_id, file_ref.file_id
                                )
                                if ocr_result is None or not ocr_result.text.strip():
                                    st.error("Run OCR first to capture label examples.")
                                else:
                                    label = services["label_service"].create_label(
                                        new_label.strip(), "{}", ""
                                    )
                                    default_llm = (
                                        f"Identify {new_label.strip()}, "
                                        "look for data that indicates this document type."
                                    )
                                    services["storage"].update_label_llm(
                                        label.label_id, default_llm
                                    )
                                    services["label_service"].attach_example(
                                        label.label_id, file_ref.file_id
                                    )
                                    services["label_service"].process_examples(
                                        label.label_id, job_id=job_id
                                    )
                                    labels_data, label_id_map, using_json_fallback = (
                                        _load_labels_from_storage(services["storage"])
                                    )
                                    label_names = [
                                        label.get("name")
                                        for label in labels_data
                                        if label.get("name")
                                    ]
                                    current_selections[file_ref.file_id] = new_label.strip()
                                    st.session_state[clear_key] = True
                                    st.success("Label created.")
                                    _trigger_rerun()
                            except Exception as exc:
                                st.error(f"Create label failed: {exc}")

                result = classification_results.get(file_ref.file_id)
                if result:
                    score_pct = f"{result['score'] * 100:.1f}%"
                    status = result["status"]
                    candidates = result.get("candidates") or []
                    best_candidate_name = None
                    if candidates:
                        best_candidate_id, _ = candidates[0]
                        best_candidate_name = label_name_by_id.get(
                            best_candidate_id, best_candidate_id
                        )
                    label_name = result["label"] or best_candidate_name or "—"
                    suffix = "" if result["label"] else " (best candidate)"
                    st.write(f"Rule-based classification: {label_name} ({score_pct}){suffix}")
                    method = result.get("method") or "unknown"
                    threshold = result.get("threshold")
                    if threshold is not None:
                        threshold_pct = f"{threshold * 100:.1f}%"
                        below = "below threshold" if result["score"] < threshold else "meets threshold"
                        st.caption(
                            f"Similarity: {score_pct} via {method} (threshold {threshold_pct}, {below})"
                        )
                    else:
                        st.caption(f"Similarity: {score_pct} via {method}")
                    st.caption(f"Status: {status}")
                    if candidates:
                        rows = []
                        for candidate_id, candidate_score in candidates:
                            candidate_name = label_name_by_id.get(candidate_id, candidate_id)
                            rows.append(
                                {
                                    "Label": candidate_name,
                                    "Score": f"{candidate_score * 100:.1f}%",
                                }
                            )
                        with st.expander("All candidate scores", expanded=False):
                            st.table(rows)
                elif file_ref.file_id in stored_assignments:
                    assignment = stored_assignments[file_ref.file_id]
                    assignment_label = None
                    assignment_label_id = getattr(assignment, "label_id", None)
                    if assignment_label_id:
                        assignment_label = label_name_by_id.get(
                            assignment_label_id, assignment_label_id
                        )
                    score = float(getattr(assignment, "score", 0.0) or 0.0)
                    status = str(getattr(assignment, "status", NO_MATCH))
                    label_text = assignment_label or "—"
                    st.write(f"Stored classification: {label_text} ({score * 100:.1f}%)")
                    st.caption(f"Status: {status}")

                llm_signals: list[str] = []
                llm_override = llm_overrides.get(file_ref.file_id)
                if llm_override:
                    st.write(f"LLM suggestion: {llm_override} (OVERRIDDEN)")
                else:
                    llm_result: LLMLabelClassification | None = llm_classifications.get(
                        file_ref.file_id
                    )
                    llm_called = result.get("llm_called") if result else False
                    if llm_result is None:
                        if llm_called:
                            st.write("LLM suggestion: — (no result)")
                        else:
                            st.write("LLM suggestion: — (not invoked)")
                    else:
                        llm_label = llm_result.label_name
                        llm_confidence = llm_result.confidence
                        llm_signals = [str(signal) for signal in llm_result.signals]
                        if llm_label:
                            llm_score_pct = f"{llm_confidence * 100:.1f}%"
                            st.write(f"LLM suggestion: {llm_label} ({llm_score_pct})")
                        else:
                            st.write("LLM suggestion: Abstained")
                if llm_signals:
                    with st.expander("LLM signals", expanded=False):
                        st.write(", ".join(llm_signals))

                if fallback_candidate_names and job_id:
                    llm_override_key = f"llm_override_{file_ref.file_id}"
                    override_options = ["(no override)"] + fallback_candidate_names
                    current_override = llm_overrides.get(file_ref.file_id)
                    override_index = (
                        override_options.index(current_override)
                        if current_override in override_options
                        else 0
                    )
                    override_choice = st.selectbox(
                        "LLM fallback override",
                        override_options,
                        index=override_index,
                        key=llm_override_key,
                    )
                    new_override = (
                        None if override_choice == "(no override)" else override_choice
                    )
                    if new_override != current_override:
                        try:
                            token = ensure_access_token(access_token, client_id, client_secret)
                            services = _get_services(token, sqlite_path)
                            if new_override:
                                updated_at = datetime.now(timezone.utc).isoformat()
                                services["storage"].set_llm_label_override(
                                    job_id,
                                    file_ref.file_id,
                                    new_override,
                                    updated_at,
                                )
                                llm_overrides[file_ref.file_id] = new_override
                            else:
                                services["storage"].clear_llm_label_override(
                                    job_id, file_ref.file_id
                                )
                                llm_overrides.pop(file_ref.file_id, None)
                            _trigger_rerun()
                        except Exception as exc:
                            st.error(f"LLM override update failed: {exc}")

                if job_id:
                    with st.expander("Extracted fields", expanded=False):
                        try:
                            token = ensure_access_token(access_token, client_id, client_secret)
                            services = _get_services(token, sqlite_path)
                            extraction = services["storage"].get_extraction(
                                job_id, file_ref.file_id
                            )
                        except Exception as exc:
                            st.error(f"Extraction lookup failed: {exc}")
                            extraction = None
                        if not extraction:
                            st.info("<<<PENDING_EXTRACTION>>>")
                        else:
                            parsed = _parse_extraction_payload(extraction)
                            fields = parsed.get("fields", {})
                            if fields:
                                rows = [
                                    {"Field": key, "Value": fields[key]}
                                    for key in sorted(fields.keys())
                                ]
                                st.table(rows)
                            else:
                                st.info("No fields extracted.")
                            if parsed.get("needs_review"):
                                st.warning("Needs review.")
                            warnings = parsed.get("warnings", [])
                            if warnings:
                                st.caption("Warnings")
                                st.write(", ".join(warnings))
                            confidences = parsed.get("confidences", {})
                            if confidences:
                                with st.expander("Confidences", expanded=False):
                                    rows = [
                                        {"Field": key, "Confidence": confidences[key]}
                                        for key in sorted(confidences.keys())
                                    ]
                                    st.table(rows)

                if job_id:
                    with st.container():
                        col_ocr, col_classify, col_extract = st.columns(3)
                        if col_ocr.button(
                            "Run OCR",
                            key=f"run_ocr_{file_ref.file_id}",
                        ):
                            try:
                                token = ensure_access_token(
                                    access_token, client_id, client_secret
                                )
                                services = _get_services(token, sqlite_path)
                                with st.spinner("Running OCR..."):
                                    services["ocr_service"].run_ocr(
                                        job_id, [file_ref.file_id]
                                    )
                                st.session_state["ocr_refresh_token"] = str(uuid4())
                                st.success("OCR completed.")
                                _trigger_rerun()
                            except Exception as exc:
                                st.error(f"OCR failed: {exc}")
                        if col_classify.button(
                            "Classify file",
                            key=f"classify_file_{file_ref.file_id}",
                        ):
                            try:
                                token = ensure_access_token(
                                    access_token, client_id, client_secret
                                )
                                services = _get_services(token, sqlite_path)
                                details = services["label_classification_service"].classify_file(
                                    job_id, file_ref.file_id
                                )
                                label_id = details.get("label_id")
                                status = details.get("status", NO_MATCH)
                                score = float(details.get("score", 0.0))
                                label_name = label_name_by_id.get(label_id)
                                classification_results[file_ref.file_id] = {
                                    "label": label_name,
                                    "score": score,
                                    "status": status,
                                    "method": details.get("method"),
                                    "threshold": details.get("threshold"),
                                    "llm_called": details.get("llm_called", False),
                                    "llm_result": details.get("llm_result"),
                                    "candidates": details.get("candidates", []),
                                }
                                st.session_state["classification_results"] = (
                                    classification_results
                                )
                                if status == MATCHED and label_name:
                                    current_selections[file_ref.file_id] = label_name
                                    suggestions = _build_suggested_names(
                                        files, current_selections
                                    )
                                    rename_key = f"edit_{file_ref.file_id}"
                                    st.session_state[rename_key] = suggestions.get(
                                        file_ref.file_id, ""
                                    )
                                else:
                                    current_selections[file_ref.file_id] = None
                                st.success("Classification completed.")
                                _trigger_rerun()
                            except Exception as exc:
                                st.error(f"Classification failed: {exc}")
                        col_classify.caption("Uses OCR text.")
                        if col_extract.button(
                            "Extract fields",
                            key=f"extract_file_{file_ref.file_id}",
                        ):
                            try:
                                token = ensure_access_token(
                                    access_token, client_id, client_secret
                                )
                                services = _get_services(token, sqlite_path)
                                with st.spinner("Extracting fields..."):
                                    services["extraction_service"].extract_fields_for_file(
                                        job_id, file_ref.file_id
                                    )
                                st.success("Extraction completed.")
                                _trigger_rerun()
                            except Exception as exc:
                                st.error(f"Extraction failed: {exc}")
                        col_extract.caption("Uses source image/PDF, not OCR text.")

                suggestions = _build_suggested_names(files, current_selections)
                suggested_name = suggestions.get(file_ref.file_id, "")
                effective_label = current_selections.get(file_ref.file_id)
                rename_key = f"edit_{file_ref.file_id}"
                if effective_label and (
                    previous_label != effective_label or not st.session_state.get(rename_key)
                ):
                    st.session_state[rename_key] = suggested_name
                new_name = st.text_input(
                    "Rename file",
                    value=st.session_state.get(rename_key, ""),
                    key=rename_key,
                )
                if new_name.strip():
                    edits[file_ref.file_id] = new_name
                if st.button(
                    "Apply rename for this file",
                    key=f"apply_rename_{file_ref.file_id}",
                ):
                    if not job_id:
                        st.error("No job is active.")
                    elif not new_name.strip():
                        st.error("Enter a new filename first.")
                    else:
                        try:
                            token = ensure_access_token(
                                access_token, client_id, client_secret
                            )
                            services = _get_services(token, sqlite_path)
                            ops = services["rename_service"].preview_manual_rename(
                                job_id, {file_ref.file_id: new_name}
                            )
                            if not ops:
                                st.info("No rename operation generated.")
                            else:
                                services["rename_service"].apply_rename(job_id, ops)
                                st.session_state["files"] = services[
                                    "jobs_service"
                                ].list_files(job_id)
                                st.success("Rename applied.")
                                _trigger_rerun()
                        except Exception as exc:
                            st.error(f"Rename failed: {exc}")

                if job_id:
                    with st.expander("View OCR", expanded=False):
                        try:
                            token = ensure_access_token(access_token, client_id, client_secret)
                            services = _get_services(token, sqlite_path)
                            ocr_result = services["storage"].get_ocr_result(
                                job_id, file_ref.file_id
                            )
                            ocr_text = ocr_result.text if ocr_result else ""
                            if not ocr_text.strip():
                                st.info("No OCR yet.")
                            refresh_token = st.session_state.get("ocr_refresh_token", "init")
                            area_key = f"ocr_{job_id}_{file_ref.file_id}_{refresh_token}"
                            st.session_state[area_key] = ocr_text
                            st.text_area(
                                "OCR Text",
                                value=st.session_state[area_key],
                                height=200,
                                key=area_key,
                                disabled=True,
                            )
                        except Exception as exc:
                            st.error(f"OCR lookup failed: {exc}")

                if job_id:
                    with st.expander("Preview file", expanded=False):
                        preview_key = f"preview_toggle_{file_ref.file_id}"
                        load_preview = st.toggle(
                            "Load preview",
                            value=False,
                            key=preview_key,
                        )
                        if load_preview:
                            try:
                                token = ensure_access_token(
                                    access_token, client_id, client_secret
                                )
                                services = _get_services(token, sqlite_path)
                                file_bytes = services["drive"].download_file_bytes(
                                    file_ref.file_id
                                )
                                if len(file_bytes) > _PREVIEW_MAX_BYTES:
                                    st.info("Preview skipped (file too large).")
                                elif file_ref.mime_type.startswith("image/"):
                                    st.image(file_bytes, width="stretch")
                                elif file_ref.mime_type == "application/pdf":
                                    rendered = False
                                    if hasattr(st, "pdf"):
                                        try:
                                            st.pdf(file_bytes)
                                            rendered = True
                                        except Exception:
                                            rendered = False
                                    if not rendered:
                                        encoded = base64.b64encode(file_bytes).decode(
                                            "ascii"
                                        )
                                        html = (
                                            f'<object data="data:application/pdf;base64,{encoded}" '
                                            'type="application/pdf" width="100%" height="600">'
                                            "PDF preview unavailable. Use download below."
                                            "</object>"
                                        )
                                        components.html(html, height=620)
                                    st.download_button(
                                        "Download PDF",
                                        data=file_bytes,
                                        file_name=file_ref.name,
                                        mime="application/pdf",
                                    )
                                else:
                                    st.info("Preview not available for this file type.")
                            except Exception as exc:
                                st.error(f"Preview failed: {exc}")
                        else:
                            st.caption("Preview loads on demand to keep the UI responsive.")
        st.session_state["label_selections"] = current_selections
        _persist_job_file_widget_state()
    else:
        edits = {}

    if preview_clicked:
        try:
            token = ensure_access_token(access_token, client_id, client_secret)
            services = _get_services(token, sqlite_path)
            if job_id is None:
                raise RuntimeError("No job has been created yet.")
            ops = services["rename_service"].preview_manual_rename(job_id, edits)
            st.session_state["preview_ops"] = ops
            st.session_state["preview_notice"] = (
                "" if ops else "No rename operations to preview."
            )
        except Exception as exc:
            st.error(f"Preview failed: {exc}")

    preview_ops = st.session_state.get("preview_ops", [])
    preview_notice = st.session_state.get("preview_notice", "")
    if preview_ops or preview_notice:
        _render_preview_plan(preview_container, preview_ops, preview_notice)

    if apply_clicked:
        try:
            token = ensure_access_token(access_token, client_id, client_secret)
            services = _get_services(token, sqlite_path)
            if job_id is None:
                raise RuntimeError("No job has been created yet.")
            ops = st.session_state.get("preview_ops") or services["rename_service"].preview_manual_rename(
                job_id, edits
            )
            services["rename_service"].apply_rename(job_id, ops)
            st.success("Rename applied.")
        except Exception as exc:
            st.error(f"Apply rename failed: {exc}")

    if undo_clicked:
        try:
            token = ensure_access_token(access_token, client_id, client_secret)
            services = _get_services(token, sqlite_path)
            if job_id is None:
                raise RuntimeError("No job has been created yet.")
            services["rename_service"].undo_last(job_id)
            st.success("Undo completed.")
        except Exception as exc:
            st.error(f"Undo failed: {exc}")


if __name__ == "__main__":
    main()
