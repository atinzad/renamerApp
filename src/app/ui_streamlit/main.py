from __future__ import annotations

import http.server
import socketserver
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import keyring
import requests
import streamlit as st

_SRC_ROOT = Path(__file__).resolve().parents[2]
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from app.container import build_services

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


def _set_keyring_value(key: str, value: str) -> None:
    try:
        keyring.set_password(_KEYRING_SERVICE, key, value)
    except Exception as exc:
        raise RuntimeError("Failed to store credentials in the OS keychain.") from exc


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


def main() -> None:
    st.title("Google Drive Image Renamer")
    _init_state()

    stored_client_id = _get_keyring_value(_KEYRING_CLIENT_ID) or ""
    stored_client_secret = _get_keyring_value(_KEYRING_CLIENT_SECRET) or ""

    st.subheader("Google Login (Recommended)")
    client_id = st.text_input("OAuth Client ID", value=stored_client_id)
    client_secret = st.text_input("OAuth Client Secret", value=stored_client_secret, type="password")
    sign_in_clicked = st.button("Sign in with Google")
    if sign_in_clicked:
        if not client_id or not client_secret:
            st.error("Client ID and Client Secret are required for OAuth.")
        else:
            global _OAUTH_STATE, _OAUTH_CODE, _OAUTH_ERROR
            _OAUTH_STATE = str(uuid4())
            _OAUTH_CODE = None
            _OAUTH_ERROR = None
            _OAUTH_EVENT.clear()
            _start_oauth_callback_server()
            auth_url = _build_auth_url(client_id, _OAUTH_STATE)
            st.session_state["oauth_in_progress"] = True
            st.session_state["oauth_auth_url"] = auth_url
            st.info("Click the link below to authorize, then return here.")

    if st.session_state.get("oauth_in_progress") and st.session_state.get("oauth_auth_url"):
        st.markdown(f"[Authorize Google Drive]({st.session_state['oauth_auth_url']})")
        if _OAUTH_EVENT.is_set():
            if _OAUTH_ERROR:
                st.error(f"OAuth error: {_OAUTH_ERROR}")
            else:
                try:
                    token_data = _exchange_code_for_token(_OAUTH_CODE, client_id, client_secret)
                    access_token = token_data.get("access_token", "")
                    refresh_token = token_data.get("refresh_token")
                    if not access_token:
                        raise RuntimeError("OAuth did not return an access token.")
                    if refresh_token:
                        _set_keyring_value(_KEYRING_REFRESH_TOKEN, refresh_token)
                    _set_keyring_value(_KEYRING_CLIENT_ID, client_id)
                    _set_keyring_value(_KEYRING_CLIENT_SECRET, client_secret)
                    expires_in = int(token_data.get("expires_in", 3600))
                    st.session_state["access_token"] = access_token
                    st.session_state["access_expires_at"] = time.time() + expires_in - 60
                    st.session_state["oauth_in_progress"] = False
                    st.success("Google Drive authorization successful.")
                except Exception as exc:
                    st.error(f"OAuth token exchange failed: {exc}")

    st.subheader("Manual Access Token (Fallback)")
    access_token = st.text_input("Access Token", type="password")
    folder_id = st.text_input("Folder ID")
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
            job = services["jobs_service"].create_job(folder_id)
            files = services["jobs_service"].list_files(job.job_id)
            st.session_state["job_id"] = job.job_id
            st.session_state["files"] = files
            st.session_state["preview_ops"] = []
            st.info(f"Listed {len(files)} files from Drive. Job ID: {job.job_id}")
        except Exception as exc:
            st.error(f"List files failed: {exc}")

    job_id = st.session_state.get("job_id")
    if job_id:
        st.subheader("Job")
        st.write(f"Job ID: {job_id}")

    files = st.session_state.get("files", [])
    if files:
        st.subheader("Files")
        for file_ref in files:
            st.write(f"{file_ref.name} ({file_ref.file_id})")

        st.subheader("Manual Rename Editor")
        edits = {}
        for file_ref in files:
            key = f"edit_{file_ref.file_id}"
            new_name = st.text_input(
                f"New name for {file_ref.name}",
                value=st.session_state.get(key, ""),
                key=key,
            )
            if new_name.strip():
                edits[file_ref.file_id] = new_name
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
