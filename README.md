# Google Drive Image Renamer (Increment 1)

This project provides the Increment 1 foundation for renaming images in a Google
Drive folder. It includes domain logic, ports, adapters (Google Drive + SQLite),
and a minimal Streamlit UI for manual rename preview, apply, and undo.

Increment 1 scope:
- Create jobs and list files from a folder
- Preview manual rename plan with sanitization and collision handling
- Apply renames and save an undo log
- Undo the last rename operation

## Project Layout
- `src/app/domain/` — dataclasses and pure rename logic
- `src/app/ports/` — Drive and Storage interfaces
- `src/app/adapters/` — Google Drive + SQLite implementations
- `src/app/services/` — application services
- `src/app/ui_streamlit/` — Streamlit UI entrypoint

## Run Locally (uv)
1) Create the environment and install dependencies:
```bash
uv sync
```

2) Activate the virtual environment:
```bash
source .venv/bin/activate
```

3) Start the Streamlit UI:
```bash
PYTHONPATH=src streamlit run src/app/ui_streamlit/main.py
```

3) In the UI, enter:
- Access Token (Google Drive API v3 bearer token)
- Folder ID (Drive folder to scan)
- SQLite Path (defaults to `./app.db`)

Then use:
- List Files — loads files into a job
- Preview — shows the rename plan
- Apply Rename — renames files and saves undo
- Undo Rename — reverts the last rename batch

## Authentication (OAuth)
Users cannot sign in with a raw email/password. Google Drive access requires OAuth.
Recommended: use the built-in OAuth flow so you do not have to paste access tokens.

Steps:
1) In Google Cloud Console, enable the Google Drive API in the same project as the OAuth client.
2) Create OAuth credentials (Desktop or Web).
3) Add the redirect URI: `http://localhost:8080/`.
4) If the consent screen is in Testing, add your Google account as a Test user.
5) In the UI, enter the Client ID and Client Secret, then click "Sign in with Google".

The app stores the refresh token securely in the OS keychain via `keyring`.
Manual access token entry is still available as a fallback.

### Manual OAuth code flow (no localhost callback)
If `http://localhost:8080/` is not reachable (for example when running in WSL or a remote VM),
use the manual OAuth code flow:
1) Click "Sign in with Google" to generate the authorization link.
2) Complete consent and copy the redirect URL (or the `code=` value).
3) Paste the redirect URL in "Redirect URL (optional)" and click "Extract code".
4) Click "Exchange code" to obtain a session access token.

### Sharing with end users
To let users sign in without being added as Test users, publish the OAuth consent screen.
This requires completing Google's OAuth verification for sensitive scopes like Drive.
Until verification is approved, only Test users can authorize the app.

## Development Notes
- If you do not have `uv` installed, see https://github.com/astral-sh/uv.
- Dependencies are defined in `pyproject.toml`.

## Notes
- Increment 1 only: no OCR, labels, or report generation.
- The Drive adapter returns all files in the folder.
