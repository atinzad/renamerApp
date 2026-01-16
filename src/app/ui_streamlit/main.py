from __future__ import annotations

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

_SRC_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _SRC_ROOT.parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

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


def _labels_path() -> Path:
    return _REPO_ROOT / "labels.json"


def _load_labels_json() -> list[dict]:
    path = _labels_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return normalize_labels_llm(data)
    return []


def _trigger_rerun() -> None:
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def _save_labels_json(labels: list[dict]) -> None:
    path = _labels_path()
    path.write_text(json.dumps(labels, indent=2, sort_keys=True))


def _upsert_label_example(labels: list[dict], label_name: str, ocr_text: str) -> list[dict]:
    normalized = label_name.strip()
    if not normalized:
        return labels
    updated = False
    for label in labels:
        if label.get("name") == normalized:
            examples = label.get("examples", [])
            if ocr_text and ocr_text not in examples:
                examples.append(ocr_text)
            label["examples"] = examples
            updated = True
            break
    if not updated:
        labels.append(
            {"name": normalized, "examples": [ocr_text] if ocr_text else [], "llm": ""}
        )
    return labels


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

    env_values = _load_env_file(_REPO_ROOT / ".env")
    stored_client_id = _get_keyring_value(_KEYRING_CLIENT_ID) or ""
    stored_client_secret = _get_keyring_value(_KEYRING_CLIENT_SECRET) or ""
    env_client_id = env_values.get("OAUTH_CLIENT_ID", "")
    env_client_secret = env_values.get("OAUTH_CLIENT_SECRET", "")
    env_folder_id = env_values.get("FOLDER_ID", "")
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
    sqlite_path = st.text_input("SQLite Path", value="./app.db")

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
            st.session_state["ocr_ready"] = False
            st.info(f"Listed {len(files)} files from Drive. Job ID: {job.job_id}")
        except Exception as exc:
            st.error(f"List files failed: {exc}")

    job_id = st.session_state.get("job_id")
    if job_id:
        st.subheader("Job")
        st.write(f"Job ID: {job_id}")

        report_cols = st.columns(5)
        run_ocr_clicked = report_cols[0].button(
            "Run OCR",
            disabled=job_id is None,
        )
        classify_clicked = report_cols[1].button("Classify files")
        fallback_clicked = report_cols[2].button("Classify fallback labels (LLM)")
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
                    labels_data = _load_labels_json()
                    for file_ref in st.session_state.get("files", []):
                        ocr_result = services["storage"].get_ocr_result(
                            job_id, file_ref.file_id
                        )
                        if ocr_result is None or not ocr_result.text.strip():
                            results[file_ref.file_id] = {
                                "label": None,
                                "score": 0.0,
                                "status": NO_MATCH,
                            }
                            continue
                        label, score, status = _classify_with_labels(
                            labels_data, ocr_result.text
                        )
                        results[file_ref.file_id] = {
                            "label": label,
                            "score": score,
                            "status": status,
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
                    st.success("Classification completed.")
                except Exception as exc:
                    st.error(f"Classification failed: {exc}")
        if fallback_clicked:
            if not st.session_state.get("ocr_ready"):
                st.error("Run OCR first.")
            else:
                try:
                    token = _ensure_access_token(access_token, client_id, client_secret)
                    services = _get_services(token, sqlite_path)
                    with st.spinner("Classifying fallback labels..."):
                        services["llm_fallback_label_service"].classify_unlabeled_files(
                            job_id
                        )
                    st.success("Fallback classification completed.")
                    _trigger_rerun()
                except Exception as exc:
                    st.error(f"Fallback classification failed: {exc}")

    files = st.session_state.get("files", [])
    edits: dict[str, str] = {}
    label_selections = st.session_state.get("label_selections", {})
    labels_data = _load_labels_json()
    label_names = [label.get("name") for label in labels_data if label.get("name")]
    fallback_candidates = list_fallback_candidates(labels_data)
    fallback_candidate_names = [candidate.name for candidate in fallback_candidates]
    classification_results = st.session_state.get("classification_results", {})
    llm_classifications: dict[str, tuple[str | None, float, list[str]]] = {}
    llm_overrides: dict[str, str] = {}
    if job_id:
        try:
            token = _ensure_access_token(access_token, client_id, client_secret)
            services = _get_services(token, sqlite_path)
            llm_classifications = services["storage"].list_llm_label_classifications(job_id)
            llm_overrides = services["storage"].list_llm_label_overrides(job_id)
        except Exception as exc:
            st.error(f"LLM fallback lookup failed: {exc}")
    if files:
        st.subheader("Files")
        current_selections = dict(label_selections)
        for file_ref in files:
            with st.expander(f"**{file_ref.name}**", expanded=True):
                st.caption(f"{file_ref.file_id}")
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
                if selected_label and selected_label != previous_label and job_id:
                    try:
                        token = _ensure_access_token(access_token, client_id, client_secret)
                        services = _get_services(token, sqlite_path)
                        ocr_result = services["storage"].get_ocr_result(
                            job_id, file_ref.file_id
                        )
                        if ocr_result and ocr_result.text.strip():
                            labels_data = _upsert_label_example(
                                labels_data, selected_label, ocr_result.text
                            )
                            _save_labels_json(labels_data)
                    except Exception:
                        pass

                new_label_key = f"new_label_{file_ref.file_id}"
                new_label = st.text_input(
                    "Create new label",
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
                            token = _ensure_access_token(access_token, client_id, client_secret)
                            services = _get_services(token, sqlite_path)
                            ocr_result = services["storage"].get_ocr_result(
                                job_id, file_ref.file_id
                            )
                            if ocr_result is None or not ocr_result.text.strip():
                                st.error("Run OCR first to capture label examples.")
                            else:
                                labels_data = _upsert_label_example(
                                    labels_data, new_label.strip(), ocr_result.text
                                )
                                _save_labels_json(labels_data)
                                label_names = [
                                    label.get("name")
                                    for label in labels_data
                                    if label.get("name")
                                ]
                                current_selections[file_ref.file_id] = new_label.strip()
                                st.session_state[new_label_key] = ""
                                st.success("Label created.")
                        except Exception as exc:
                            st.error(f"Create label failed: {exc}")

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

                result = classification_results.get(file_ref.file_id)
                if result:
                    score_pct = f"{result['score'] * 100:.1f}%"
                    status = result["status"]
                    label_name = result["label"] or ""
                    st.write(f"Classification: {label_name} | {score_pct} | {status}")

                llm_override = llm_overrides.get(file_ref.file_id)
                if llm_override:
                    st.write(f"LLM Fallback Label: {llm_override} (OVERRIDDEN)")
                else:
                    llm_result = llm_classifications.get(file_ref.file_id)
                    if llm_result is None:
                        st.write("LLM Fallback Label: —")
                    else:
                        llm_label, llm_confidence, llm_signals = llm_result
                        if llm_label:
                            llm_score_pct = f"{llm_confidence * 100:.1f}%"
                            st.write(f"LLM Fallback Label: {llm_label} ({llm_score_pct})")
                        else:
                            st.write("LLM Fallback Label: Abstained")
                        if llm_signals:
                            with st.expander("LLM signals"):
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

                if job_id and st.session_state.get("ocr_ready"):
                    with st.expander("View OCR"):
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
            else:
                st.info("No rename operations to preview.")
        except Exception as exc:
            st.error(f"Preview failed: {exc}")

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
