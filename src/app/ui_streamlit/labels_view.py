from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import streamlit as st

from app.domain.similarity import normalize_text_to_tokens
from app.ui_streamlit.helpers import _trigger_rerun


def render_labels_view(
    access_token: str,
    sqlite_path: str,
    get_services: Callable[[str, str], dict[str, Any]],
) -> None:
    st.subheader("Labels")
    try:
        services = get_services(access_token, sqlite_path)
        labels = services["storage"].list_labels(include_inactive=True)
    except Exception as exc:
        st.error(f"Failed to load labels: {exc}")
        return
    if not labels:
        st.info("No labels found in SQLite.")
        return
    for label in labels:
        status = "Active" if label.is_active else "Inactive"
        with st.expander(f"{label.name} ({status})", expanded=False):
            schema_key = f"schema_{label.label_id}"
            refresh_schema_key = f"refresh_schema_{label.label_id}"
            if st.session_state.get(refresh_schema_key):
                st.session_state[schema_key] = label.extraction_schema_json or "{}"
                st.session_state[f"instructions_{label.label_id}"] = (
                    label.extraction_instructions or ""
                )
                st.session_state[f"llm_instruction_{label.label_id}"] = label.llm or ""
                st.session_state[refresh_schema_key] = False
            schema_value = st.text_area(
                "Extraction schema (JSON)",
                value=label.extraction_schema_json or "{}",
                key=schema_key,
                height=200,
            )
            if st.button("Save schema", key=f"save_schema_{label.label_id}"):
                try:
                    json.loads(schema_value or "{}")
                except json.JSONDecodeError as exc:
                    st.error(f"Invalid JSON: {exc}")
                else:
                    try:
                        services["storage"].update_label_extraction_schema(
                            label.label_id, schema_value.strip()
                        )
                        st.success("Schema saved.")
                        st.session_state[refresh_schema_key] = True
                        _trigger_rerun()
                    except Exception as exc:
                        st.error(f"Save failed: {exc}")
            _render_field_descriptions(
                label.label_id, schema_value or "{}", schema_key, services
            )
            instructions_key = f"instructions_{label.label_id}"
            instructions_value = st.text_area(
                "Extraction instructions",
                value=label.extraction_instructions or "",
                key=instructions_key,
                height=140,
            )
            if st.button(
                "Save instructions",
                key=f"save_instructions_{label.label_id}",
            ):
                try:
                    services["storage"].update_label_extraction_instructions(
                        label.label_id, instructions_value.strip()
                    )
                    st.success("Instructions saved.")
                except Exception as exc:
                    st.error(f"Save failed: {exc}")
            llm_key = f"llm_instruction_{label.label_id}"
            llm_value = st.text_area(
                "LLM label instruction",
                value=label.llm or "",
                key=llm_key,
                height=120,
            )
            if st.button(
                "Save LLM instruction",
                key=f"save_llm_{label.label_id}",
            ):
                try:
                    services["storage"].update_label_llm(
                        label.label_id, llm_value.strip()
                    )
                    st.success("LLM instruction saved.")
                except Exception as exc:
                    st.error(f"Save failed: {exc}")
            with st.expander("Build schema from examples", expanded=False):
                st.caption("Uses all stored OCR examples for this label.")
                schema_hint_key = f"schema_hint_{label.label_id}"
                schema_hint = st.text_area(
                    "Optional schema guidance",
                    value=st.session_state.get(schema_hint_key, ""),
                    key=schema_hint_key,
                    height=120,
                    help="Provide extra context or constraints to guide schema generation.",
                )
                if st.button(
                    "Generate schema",
                    key=f"generate_schema_{label.label_id}",
                ):
                    try:
                        examples = services["storage"].list_label_examples(label.label_id)
                        ocr_texts: list[str] = []
                        for example in examples:
                            features = services["storage"].get_label_example_features(
                                example.example_id
                            )
                            if features and features.get("ocr_text"):
                                ocr_texts.append(features["ocr_text"])
                        if not ocr_texts:
                            st.error("No OCR examples available for this label.")
                        else:
                            combined = "\n\n".join(ocr_texts)
                            with st.spinner("Generating schema..."):
                                services["schema_builder_service"].build_from_ocr(
                                    label.label_id,
                                    combined,
                                    schema_hint,
                                )
                            st.success("Schema generated from examples.")
                            st.session_state[refresh_schema_key] = True
                            _trigger_rerun()
                    except Exception as exc:
                        st.error(f"Schema generation failed: {exc}")
            with st.expander("Examples", expanded=False):
                try:
                    examples = services["storage"].list_label_examples(label.label_id)
                except Exception as exc:
                    st.error(f"Failed to load examples: {exc}")
                    examples = []
                if not examples:
                    st.info("No examples for this label yet.")
                else:
                    for example in examples:
                        features = services["storage"].get_label_example_features(
                            example.example_id
                        )
                        example_key = f"example_{example.example_id}"
                        st.caption(f"{example.filename} ({example.file_id})")
                        st.text_area(
                            "Example OCR text",
                            value=features.get("ocr_text", "") if features else "",
                            key=example_key,
                            height=140,
                        )
                        if st.button(
                            "Delete example",
                            key=f"delete_example_{example.example_id}",
                        ):
                            try:
                                services["storage"].delete_label_example(example.example_id)
                                st.success("Example deleted.")
                                _trigger_rerun()
                            except Exception as exc:
                                st.error(f"Failed to delete example: {exc}")
                    if st.button(
                        "Save examples",
                        key=f"save_examples_{label.label_id}",
                    ):
                        for example in examples:
                            example_key = f"example_{example.example_id}"
                            updated_text = st.session_state.get(example_key, "")
                            try:
                                tokens = normalize_text_to_tokens(updated_text or "")
                                embedding = None
                                try:
                                    embedding = services["embeddings"].embed_text(
                                        updated_text or ""
                                    )
                                except Exception:
                                    embedding = None
                                services["storage"].save_label_example_features(
                                    example.example_id,
                                    updated_text or "",
                                    embedding,
                                    tokens,
                                )
                            except Exception as exc:
                                st.error(f"Failed to save example: {exc}")
                                break
                        else:
                            st.success("Examples saved.")
                st.divider()
                st.caption("Add example (paste OCR text)")
                new_example_key = f"new_example_{label.label_id}"
                new_example_text = st.text_area(
                    "New example OCR text",
                    value=st.session_state.get(new_example_key, ""),
                    key=new_example_key,
                    height=140,
                )
                if st.button(
                    "Add example",
                    key=f"add_example_{label.label_id}",
                ):
                    if not new_example_text.strip():
                        st.error("Paste OCR text first.")
                    else:
                        try:
                            file_id = f"manual:{uuid4()}"
                            filename = "manual_ocr.txt"
                            example = services["storage"].attach_label_example(
                                label.label_id,
                                file_id,
                                filename,
                            )
                            tokens = normalize_text_to_tokens(new_example_text)
                            embedding = None
                            try:
                                embedding = services["embeddings"].embed_text(
                                    new_example_text
                                )
                            except Exception:
                                embedding = None
                            services["storage"].save_label_example_features(
                                example.example_id,
                                new_example_text,
                                embedding,
                                tokens,
                            )
                            st.session_state[new_example_key] = ""
                            st.success("Example added.")
                            _trigger_rerun()
                        except Exception as exc:
                            st.error(f"Failed to add example: {exc}")
            st.divider()
            confirm_key = f"confirm_delete_{label.label_id}"
            confirm = st.checkbox(
                "I understand this will delete the label and its examples.",
                key=confirm_key,
            )
            if st.button("Delete label", key=f"delete_label_{label.label_id}"):
                if not confirm:
                    st.error("Confirm label deletion first.")
                else:
                    try:
                        services["storage"].delete_label(label.label_id)
                        st.success("Label deleted.")
                        _trigger_rerun()
                    except Exception as exc:
                        st.error(f"Failed to delete label: {exc}")


def _render_field_descriptions(
    label_id: str,
    schema_json: str,
    schema_key: str,
    services: dict[str, Any],
) -> None:
    try:
        parsed = json.loads(schema_json) if schema_json.strip() else {}
    except json.JSONDecodeError:
        return
    properties = parsed.get("properties", {}) if isinstance(parsed, dict) else {}
    if not isinstance(properties, dict) or not properties:
        return
    with st.expander("Field Descriptions", expanded=False):
        st.caption("Add per-field guidance to improve extraction accuracy.")
        cols = st.columns([2, 1, 4])
        cols[0].markdown("**Field**")
        cols[1].markdown("**Type**")
        cols[2].markdown("**Description**")
        for field_name, field_schema in properties.items():
            field_type = field_schema.get("type", "string") if isinstance(field_schema, dict) else "string"
            current_desc = field_schema.get("description", "") if isinstance(field_schema, dict) else ""
            cols = st.columns([2, 1, 4])
            cols[0].code(field_name, language=None)
            cols[1].text(field_type)
            desc_input = cols[2].text_input(
                f"desc_{field_name}",
                value=current_desc,
                key=f"field_desc_{label_id}_{field_name}",
                label_visibility="collapsed",
            )
        if st.button("Save descriptions", key=f"save_descs_{label_id}"):
            try:
                for field_name in properties:
                    desc_key = f"field_desc_{label_id}_{field_name}"
                    new_desc = st.session_state.get(desc_key, "").strip()
                    if new_desc:
                        if isinstance(properties[field_name], dict):
                            properties[field_name]["description"] = new_desc
                        else:
                            properties[field_name] = {"type": "string", "description": new_desc}
                    else:
                        if isinstance(properties[field_name], dict):
                            properties[field_name].pop("description", None)
                updated_json = json.dumps(parsed, indent=2)
                services["storage"].update_label_extraction_schema(
                    label_id, updated_json
                )
                st.session_state[schema_key] = updated_json
                st.success("Descriptions saved.")
                st.session_state[f"refresh_schema_{label_id}"] = True
                _trigger_rerun()
            except Exception as exc:
                st.error(f"Save failed: {exc}")
