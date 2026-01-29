from __future__ import annotations

import base64
import http.server
import json
import socketserver
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import keyring
import requests
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
from app.domain.label_fallback import list_fallback_candidates, normalize_labels_llm
from app.domain.labels import AMBIGUOUS, MATCHED, NO_MATCH, decide_match
from app.domain.similarity import jaccard_similarity, normalize_text_to_tokens

_OAUTH_SCOPE = "https://www.googleapis.com/auth/drive"
_REDIRECT_URI = "http://localhost:8080/"
_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
_KEYRING_SERVICE = "renamerapp-google-drive"
_KEYRING_REFRESH_TOKEN = "refresh_token"
_KEYRING_CLIENT_ID = "client_id"
_KEYRING_CLIENT_SECRET = "client_secret"
_OAUTH_STATE: str | None = None
_OAUTH_CODE: str | None = None
_OAUTH_ERROR: str | None = None
_OAUTH_EVENT = threading.Event()
_OAUTH_SERVER_STARTED = False
_OAUTH_RESULT_FILE = Path(tempfile.gettempdir()) / "renamerapp_oauth_result.json"
_PREVIEW_MAX_BYTES = 10 * 1024 * 1024


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
        value = value.strip().strip("\"'")  # basic quote trimming
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


def _parse_extraction_payload(extraction: dict | None) -> dict[str, object]:
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
    fields_json = extraction.get("fields_json") or ""
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
    confidences_json = extraction.get("confidences_json") or ""
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


def _render_labels_view(access_token: str, sqlite_path: str) -> None:
    st.subheader("Labels")
    try:
        services = _get_services(access_token, sqlite_path)
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
                    except Exception as exc:
                        st.error(f"Save failed: {exc}")
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
                                    label.label_id, combined
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
                                services["storage"].delete_label_example(
                                    example.example_id
                                )
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
                            example_id = None
                            file_id = f"manual:{uuid4()}"
                            filename = "manual_ocr.txt"
                            example = services["storage"].attach_label_example(
                                label.label_id,
                                file_id,
                                filename,
                            )
                            example_id = example.example_id
                            tokens = normalize_text_to_tokens(new_example_text)
                            embedding = None
                            try:
                                embedding = services["embeddings"].embed_text(
                                    new_example_text
                                )
                            except Exception:
                                embedding = None
                            services["storage"].save_label_example_features(
                                example_id,
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


def _get_keyring_value(key: str) -> str | None:
    try:
        return keyring.get_password(_KEYRING_SERVICE, key)
    except Exception:
        return None


def _set_keyring_value(key: str, value: str) -> bool:
    try:
        keyring.set_password(_KEYRING_SERVICE, key, value)
        return True
    except Exception:
        return False


def _build_auth_url(client_id: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": _REDIRECT_URI,
        "response_type": "code",
        "scope": _OAUTH_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    query = "&".join(f"{key}={requests.utils.quote(str(value))}" for key, value in params.items())
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


def _write_oauth_result(code: str | None, state: str | None, error: str | None) -> None:
    try:
        _OAUTH_RESULT_FILE.write_text(json.dumps({"code": code, "state": state, "error": error}))
    except Exception:
        return


def _read_oauth_result() -> dict | None:
    try:
        if not _OAUTH_RESULT_FILE.exists():
            return None
        raw = _OAUTH_RESULT_FILE.read_text()
        return json.loads(raw)
    except Exception:
        return None


def _clear_oauth_result() -> None:
    try:
        if _OAUTH_RESULT_FILE.exists():
            _OAUTH_RESULT_FILE.unlink()
    except Exception:
        return


def _start_oauth_callback_server() -> None:
    global _OAUTH_SERVER_STARTED
    if _OAUTH_SERVER_STARTED:
        return

    class OAuthHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            global _OAUTH_CODE, _OAUTH_ERROR
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            code = params.get("code", [None])[0]
            state = params.get("state", [None])[0]
            if not code:
                _OAUTH_ERROR = "Missing authorization code."
            elif state != _OAUTH_STATE:
                _OAUTH_ERROR = "State mismatch."
            else:
                _OAUTH_CODE = code
            _write_oauth_result(_OAUTH_CODE, state, _OAUTH_ERROR)
            _OAUTH_EVENT.set()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h3>Authorization received. You can close this tab.</h3></body></html>"
            )

        def log_message(self, format: str, *args: object) -> None:
            return

    def _serve() -> None:
        global _OAUTH_SERVER_STARTED, _OAUTH_ERROR
        try:
            with socketserver.TCPServer(("localhost", 8080), OAuthHandler) as httpd:
                httpd.handle_request()
        except OSError as exc:
            _OAUTH_ERROR = f"OAuth callback server failed to start: {exc}"
            _OAUTH_EVENT.set()
        finally:
            _OAUTH_SERVER_STARTED = False

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    _OAUTH_SERVER_STARTED = True


def _exchange_code_for_token(code: str, client_id: str, client_secret: str) -> dict:
    response = requests.post(
        _OAUTH_TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": _REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Token exchange failed: {response.status_code} {response.text}")
    return response.json()


def _refresh_access_token(refresh_token: str, client_id: str, client_secret: str) -> dict:
    response = requests.post(
        _OAUTH_TOKEN_URL,
        data={
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Token refresh failed: {response.status_code} {response.text}")
    return response.json()


def _validate_access_token(access_token: str) -> dict:
    response = requests.get(
        "https://www.googleapis.com/oauth2/v3/tokeninfo",
        params={"access_token": access_token},
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Token validation failed: {response.status_code} {response.text}")
    return response.json()


def _ensure_access_token(manual_token: str, client_id: str, client_secret: str) -> str:
    token = st.session_state.get("access_token")
    expires_at = st.session_state.get("access_expires_at", 0)
    if token and time.time() < expires_at:
        return token

    refresh_token = _get_keyring_value(_KEYRING_REFRESH_TOKEN)
    if refresh_token and client_id and client_secret:
        token_data = _refresh_access_token(refresh_token, client_id, client_secret)
        access_token = token_data.get("access_token", "")
        if not access_token:
            raise RuntimeError("Refresh token did not return an access token.")
        expires_in = int(token_data.get("expires_in", 3600))
        st.session_state["access_token"] = access_token
        st.session_state["access_expires_at"] = time.time() + expires_in - 60
        return access_token

    if manual_token:
        return manual_token

    raise RuntimeError("No access token available. Sign in or paste a manual token.")


def _extract_code_from_redirect(value: str) -> str | None:
    if not value:
        return None
    parsed = urlparse(value.strip())
    params = parse_qs(parsed.query)
    return params.get("code", [None])[0]


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
    global _OAUTH_STATE, _OAUTH_CODE, _OAUTH_ERROR
    if st.session_state.get("oauth_state"):
        _OAUTH_STATE = st.session_state.get("oauth_state")

    view = st.sidebar.radio("View", ["Job", "Labels"], index=0)

    env_values = _load_env_file(_REPO_ROOT / ".env")
    env_folder_id = env_values.get("FOLDER_ID", "")
    sqlite_path = st.text_input("SQLite Path", value="./app.db")

    if view == "Labels":
        _render_labels_view("", sqlite_path)
        return

    stored_client_id = _get_keyring_value(_KEYRING_CLIENT_ID) or ""
    stored_client_secret = _get_keyring_value(_KEYRING_CLIENT_SECRET) or ""
    env_client_id = env_values.get("OAUTH_CLIENT_ID", "")
    env_client_secret = env_values.get("OAUTH_CLIENT_SECRET", "")
    env_access_token = env_values.get("GOOGLE_DRIVE_ACCESS_TOKEN", "")
    if env_access_token and not st.session_state.get("manual_access_token"):
        st.session_state["manual_access_token"] = env_access_token

    st.subheader("Google Login (Recommended)")
    client_id = st.text_input(
        "OAuth Client ID",
        value=env_client_id or stored_client_id,
        help="Create an OAuth client in Google Cloud Console (OAuth consent + credentials).",
    )
    client_secret = st.text_input(
        "OAuth Client Secret",
        value=env_client_secret or stored_client_secret,
        type="password",
        help="Client secret from the same OAuth client.",
    )
    sign_in_clicked = st.button("Sign in with Google")
    if sign_in_clicked:
        if not client_id or not client_secret:
            st.error("Client ID and Client Secret are required for OAuth.")
        else:
            _OAUTH_STATE = str(uuid4())
            st.session_state["oauth_state"] = _OAUTH_STATE
            _OAUTH_CODE = None
            _OAUTH_ERROR = None
            _OAUTH_EVENT.clear()
            _clear_oauth_result()
            _start_oauth_callback_server()
            auth_url = _build_auth_url(client_id, _OAUTH_STATE)
            st.session_state["oauth_in_progress"] = True
            st.session_state["oauth_auth_url"] = auth_url
            st.info("Click the link below to authorize, then return here.")

    if st.session_state.get("oauth_in_progress") and st.session_state.get("oauth_auth_url"):
        st.markdown(f"[Authorize Google Drive]({st.session_state['oauth_auth_url']})")
        oauth_result = _read_oauth_result()
        if oauth_result and not _OAUTH_EVENT.is_set():
            _OAUTH_CODE = oauth_result.get("code")
            _OAUTH_ERROR = oauth_result.get("error")
            _OAUTH_EVENT.set()
        if _OAUTH_EVENT.is_set():
            if _OAUTH_ERROR:
                st.error(f"OAuth error: {_OAUTH_ERROR}")
                _clear_oauth_result()
            else:
                state = None
                if oauth_result:
                    state = oauth_result.get("state")
                if state and state != st.session_state.get("oauth_state"):
                    st.error("OAuth error: State mismatch.")
                    _clear_oauth_result()
                    return
                try:
                    token_data = _exchange_code_for_token(_OAUTH_CODE, client_id, client_secret)
                    access_token = token_data.get("access_token", "")
                    refresh_token = token_data.get("refresh_token")
                    if not access_token:
                        raise RuntimeError("OAuth did not return an access token.")
                    keyring_failed = False
                    if refresh_token:
                        keyring_failed = not _set_keyring_value(_KEYRING_REFRESH_TOKEN, refresh_token)
                    if not _set_keyring_value(_KEYRING_CLIENT_ID, client_id):
                        keyring_failed = True
                    if not _set_keyring_value(_KEYRING_CLIENT_SECRET, client_secret):
                        keyring_failed = True
                    expires_in = int(token_data.get("expires_in", 3600))
                    st.session_state["access_token"] = access_token
                    st.session_state["access_expires_at"] = time.time() + expires_in - 60
                    st.session_state["manual_access_token"] = access_token
                    st.session_state["oauth_in_progress"] = False
                    st.success("Google Drive authorization successful.")
                    if keyring_failed:
                        st.warning(
                            "Saved access token for this session, but the OS keychain is unavailable. "
                            "You'll need to sign in again next time."
                        )
                    _clear_oauth_result()
                except Exception as exc:
                    st.error(f"OAuth token exchange failed: {exc}")
                    _clear_oauth_result()

    st.caption("Redirect URL (after consent)")
    redirect_url = st.text_input(
        "Redirect URL",
        help="Paste the full redirect URL after consent to extract the authorization code.",
    )
    if st.button("Extract token"):
        if not redirect_url.strip():
            st.error("Paste the redirect URL first.")
        elif not client_id or not client_secret:
            st.error("Client ID and Client Secret are required for OAuth.")
        else:
            manual_code = _extract_code_from_redirect(redirect_url)
            if not manual_code:
                st.error("No authorization code found in the redirect URL.")
            else:
                try:
                    token_data = _exchange_code_for_token(manual_code, client_id, client_secret)
                    access_token = token_data.get("access_token", "")
                    refresh_token = token_data.get("refresh_token")
                    if not access_token:
                        raise RuntimeError("OAuth did not return an access token.")
                    keyring_failed = False
                    if refresh_token:
                        keyring_failed = not _set_keyring_value(_KEYRING_REFRESH_TOKEN, refresh_token)
                    if not _set_keyring_value(_KEYRING_CLIENT_ID, client_id):
                        keyring_failed = True
                    if not _set_keyring_value(_KEYRING_CLIENT_SECRET, client_secret):
                        keyring_failed = True
                    expires_in = int(token_data.get("expires_in", 3600))
                    st.session_state["access_token"] = access_token
                    st.session_state["access_expires_at"] = time.time() + expires_in - 60
                    st.session_state["manual_access_token"] = access_token
                    st.session_state["oauth_in_progress"] = False
                    st.success("Google Drive authorization successful.")
                    if keyring_failed:
                        st.warning(
                            "Saved access token for this session, but the OS keychain is unavailable. "
                            "You'll need to sign in again next time."
                        )
                except Exception as exc:
                    st.error(f"OAuth token exchange failed: {exc}")

    st.subheader("Manual Access Token (Fallback)")
    access_token = st.text_input(
        "Access Token",
        value=st.session_state.get("manual_access_token", ""),
        type="password",
    )
    if st.button("Validate token"):
        if not access_token:
            st.error("Access token is required to validate.")
        else:
            try:
                info = _validate_access_token(access_token)
                st.success("Token is valid.")
                st.json(info)
            except Exception as exc:
                st.error(str(exc))
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
            token = _ensure_access_token(access_token, client_id, client_secret)
            services = _get_services(token, sqlite_path)
            extracted_folder_id = _extract_folder_id(folder_id)
            if not extracted_folder_id:
                raise RuntimeError("Folder ID is required.")
            job = services["jobs_service"].create_job(extracted_folder_id)
            files = services["jobs_service"].list_files(job.job_id)
            st.session_state["job_id"] = job.job_id
            st.session_state["files"] = files
            st.session_state["preview_ops"] = []
            st.session_state["preview_notice"] = ""
            st.session_state["ocr_ready"] = False
            st.info(f"Listed {len(files)} files from Drive. Job ID: {job.job_id}")
        except Exception as exc:
            st.error(f"List files failed: {exc}")

    job_id = st.session_state.get("job_id")
    preview_container = st.container()
    if job_id:
        st.subheader("Job")
        st.write(f"Job ID: {job_id}")

        report_cols = st.columns(5)
        run_ocr_clicked = report_cols[0].button(
            "Run OCR",
            disabled=job_id is None,
        )
        report_cols[0].caption("Required before classification.")
        classify_clicked = report_cols[1].button("Classify files")
        report_cols[1].caption("Embedding + lexical, with LLM fallback on no-match.")
        extract_clicked = report_cols[2].button("Extract fields")
        report_cols[2].caption("LLM-powered field extraction.")
        preview_report_clicked = report_cols[3].button("Preview Report")
        write_report_clicked = report_cols[4].button(
            "Write Report to Folder",
            disabled=job_id is None,
        )
        if run_ocr_clicked:
            try:
                token = _ensure_access_token(access_token, client_id, client_secret)
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
                token = _ensure_access_token(access_token, client_id, client_secret)
                services = _get_services(token, sqlite_path)
                report_text = services["report_service"].preview_report(job_id)
                st.session_state["report_preview"] = report_text
                st.success("Report preview generated.")
            except Exception as exc:
                st.error(f"Report preview failed: {exc}")

        if extract_clicked:
            try:
                token = _ensure_access_token(access_token, client_id, client_secret)
                services = _get_services(token, sqlite_path)
                with st.spinner("Extracting fields..."):
                    services["extraction_service"].extract_fields_for_job(job_id)
                st.success("Extraction completed.")
                _trigger_rerun()
            except Exception as exc:
                st.error(f"Extraction failed: {exc}")

        st.text_area(
            "Report Preview",
            value=st.session_state.get("report_preview", ""),
            height=300,
        )

        if write_report_clicked:
            try:
                token = _ensure_access_token(access_token, client_id, client_secret)
                services = _get_services(token, sqlite_path)
                report_file_id = services["report_service"].write_report(job_id)
                st.success(f"Report uploaded. File ID: {report_file_id}")
            except Exception as exc:
                st.error(f"Report upload failed: {exc}")
        if classify_clicked:
            if not st.session_state.get("ocr_ready"):
                st.error("Run OCR first.")
            else:
                try:
                    token = _ensure_access_token(access_token, client_id, client_secret)
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
            token = _ensure_access_token(access_token, client_id, client_secret)
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
    llm_classifications: dict[str, tuple[str | None, float, list[str]]] = {}
    llm_overrides: dict[str, str] = {}
    storage = None
    if job_id:
        try:
            token = _ensure_access_token(access_token, client_id, client_secret)
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
        for file_ref in files:
            badges: list[str] = []
            status = ocr_status.get(file_ref.file_id)
            if status:
                if not status.get("has_ocr"):
                    badges.append("NO OCR")
                elif not status.get("has_tokens"):
                    badges.append("NO TOKENS")
            badge_text = f" [{' | '.join(badges)}]" if badges else ""
            expander_key = f"file_expander_{file_ref.file_id}"
            st.markdown(f"**{file_ref.name}**{badge_text}")
            st.caption(f"{file_ref.file_id}")
            expanded = st.toggle(
                "Show details",
                value=st.session_state.get(expander_key, False),
                key=expander_key,
            )
            if expanded:
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
                if selected_label and job_id:
                    if st.button(
                        "Add as label example",
                        key=f"add_example_{file_ref.file_id}",
                    ):
                        try:
                            token = _ensure_access_token(access_token, client_id, client_secret)
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
                                token = _ensure_access_token(
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

                llm_signals: list[str] = []
                llm_override = llm_overrides.get(file_ref.file_id)
                if llm_override:
                    st.write(f"LLM suggestion: {llm_override} (OVERRIDDEN)")
                else:
                    llm_result = llm_classifications.get(file_ref.file_id)
                    llm_called = result.get("llm_called") if result else False
                    if llm_result is None:
                        if llm_called:
                            st.write("LLM suggestion: — (no result)")
                        else:
                            st.write("LLM suggestion: — (not invoked)")
                    else:
                        llm_label, llm_confidence, llm_signals = llm_result
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
                            token = _ensure_access_token(access_token, client_id, client_secret)
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
                            token = _ensure_access_token(access_token, client_id, client_secret)
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
                                token = _ensure_access_token(
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
                                token = _ensure_access_token(
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
                        if col_extract.button(
                            "Extract fields",
                            key=f"extract_file_{file_ref.file_id}",
                        ):
                            try:
                                token = _ensure_access_token(
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
                            token = _ensure_access_token(
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
                            token = _ensure_access_token(access_token, client_id, client_secret)
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
                                token = _ensure_access_token(
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
    else:
        edits = {}

    if preview_clicked:
        try:
            token = _ensure_access_token(access_token, client_id, client_secret)
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
            token = _ensure_access_token(access_token, client_id, client_secret)
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
            token = _ensure_access_token(access_token, client_id, client_secret)
            services = _get_services(token, sqlite_path)
            if job_id is None:
                raise RuntimeError("No job has been created yet.")
            services["rename_service"].undo_last(job_id)
            st.success("Undo completed.")
        except Exception as exc:
            st.error(f"Undo failed: {exc}")


if __name__ == "__main__":
    main()
