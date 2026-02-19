from __future__ import annotations

import http.server
import json
import os
import re
import socketserver
import tempfile
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import keyring
import requests
import streamlit as st

_OAUTH_SCOPE = "https://www.googleapis.com/auth/drive"
_DEFAULT_REDIRECT_URI = "http://localhost:8080/"
_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", _DEFAULT_REDIRECT_URI).strip()
if not _REDIRECT_URI:
    _REDIRECT_URI = _DEFAULT_REDIRECT_URI
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
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _REPO_ROOT / ".env"
_ENV_ACCESS_TOKEN_PATTERN = re.compile(
    r"^\s*(?:export\s+)?GOOGLE_DRIVE_ACCESS_TOKEN\s*="
)


@dataclass(frozen=True)
class AuthInputs:
    client_id: str
    client_secret: str
    access_token: str


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
    query = "&".join(
        f"{key}={requests.utils.quote(str(value))}" for key, value in params.items()
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


def _write_oauth_result(code: str | None, state: str | None, error: str | None) -> None:
    try:
        _OAUTH_RESULT_FILE.write_text(
            json.dumps({"code": code, "state": state, "error": error})
        )
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
    callback_host, callback_port = _oauth_callback_bind_address()

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
            with socketserver.TCPServer((callback_host, callback_port), OAuthHandler) as httpd:
                httpd.handle_request()
        except OSError as exc:
            _OAUTH_ERROR = (
                f"OAuth callback server failed to start on {callback_host}:{callback_port}: {exc}"
            )
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
        raise RuntimeError(
            f"Token validation failed: {response.status_code} {response.text}"
        )
    return response.json()


def _extract_code_from_redirect(value: str) -> str | None:
    if not value:
        return None
    parsed = urlparse(value.strip())
    params = parse_qs(parsed.query)
    return params.get("code", [None])[0]


def _oauth_callback_bind_address() -> tuple[str, int]:
    parsed = urlparse(_REDIRECT_URI)
    host = parsed.hostname or "localhost"
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return host, port


def _persist_access_token_to_env(access_token: str) -> None:
    normalized = (access_token or "").strip()
    if not normalized:
        return
    entry = f'GOOGLE_DRIVE_ACCESS_TOKEN="{_escape_env_value(normalized)}"'
    try:
        lines = _ENV_FILE.read_text().splitlines() if _ENV_FILE.exists() else []
        updated = False
        for index, line in enumerate(lines):
            if _ENV_ACCESS_TOKEN_PATTERN.match(line):
                lines[index] = entry
                updated = True
                break
        if not updated:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(entry)
        _ENV_FILE.write_text("\n".join(lines) + "\n")
    except Exception:
        return


def _escape_env_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _persist_token_data(token_data: dict, client_id: str, client_secret: str) -> bool:
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
    _persist_access_token_to_env(access_token)
    return keyring_failed


def ensure_access_token(manual_token: str, client_id: str, client_secret: str) -> str:
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
        st.session_state["manual_access_token"] = access_token
        _persist_access_token_to_env(access_token)
        return access_token

    if manual_token:
        st.session_state["manual_access_token"] = manual_token
        _persist_access_token_to_env(manual_token)
        return manual_token

    raise RuntimeError("No access token available. Sign in or paste a manual token.")


def render_auth_controls(env_values: dict[str, str]) -> AuthInputs:
    global _OAUTH_STATE, _OAUTH_CODE, _OAUTH_ERROR
    if st.session_state.get("oauth_state"):
        _OAUTH_STATE = st.session_state.get("oauth_state")

    stored_client_id = _get_keyring_value(_KEYRING_CLIENT_ID) or ""
    stored_client_secret = _get_keyring_value(_KEYRING_CLIENT_SECRET) or ""
    env_client_id = env_values.get("OAUTH_CLIENT_ID", "")
    env_client_secret = env_values.get("OAUTH_CLIENT_SECRET", "")
    env_access_token = env_values.get("GOOGLE_DRIVE_ACCESS_TOKEN", "")
    if env_access_token and not st.session_state.get("manual_access_token"):
        st.session_state["manual_access_token"] = env_access_token

    st.subheader("Google Login (Recommended)")
    st.caption(f"OAuth redirect URI: `{_REDIRECT_URI}`")
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
            try:
                opened = webbrowser.open(auth_url, new=2)
                if opened:
                    st.info(
                        "Browser opened for Google authorization. Return here after approval."
                    )
                else:
                    st.info("Open the link below to authorize, then return here.")
            except Exception:
                st.info("Open the link below to authorize, then return here.")

    if st.session_state.get("oauth_in_progress"):
        if st.button("Cancel sign-in"):
            st.session_state["oauth_in_progress"] = False
            _clear_oauth_result()
            _OAUTH_EVENT.clear()
            _OAUTH_CODE = None
            _OAUTH_ERROR = None
            st.info("OAuth sign-in canceled.")

    if st.session_state.get("oauth_in_progress") and st.session_state.get(
        "oauth_auth_url"
    ):
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
                    return AuthInputs(
                        client_id=client_id,
                        client_secret=client_secret,
                        access_token=st.session_state.get("manual_access_token", ""),
                    )
                else:
                    try:
                        token_data = _exchange_code_for_token(
                            _OAUTH_CODE, client_id, client_secret
                        )
                        keyring_failed = _persist_token_data(
                            token_data, client_id, client_secret
                        )
                        st.success("Google Drive authorization successful.")
                        if keyring_failed:
                            st.warning(
                                "Saved access token for this session, but the OS keychain is unavailable. "
                                "You'll need to sign in again next time."
                            )
                        _clear_oauth_result()
                    except Exception as exc:
                        st.session_state["oauth_in_progress"] = False
                        st.error(f"OAuth token exchange failed: {exc}")
                        _clear_oauth_result()

    with st.expander("Troubleshooting (manual redirect)", expanded=False):
        st.caption("Use this only if the local callback flow does not work.")
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
                        token_data = _exchange_code_for_token(
                            manual_code, client_id, client_secret
                        )
                        keyring_failed = _persist_token_data(
                            token_data, client_id, client_secret
                        )
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
    return AuthInputs(
        client_id=client_id,
        client_secret=client_secret,
        access_token=access_token,
    )
