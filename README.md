# Google Drive Image Renamer

Rename files in a Google Drive folder with a Streamlit UI. Preview changes, apply
renames, undo the last rename, and generate/upload a per-file report.

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

## Authentication (OAuth)
Users cannot sign in with a raw email/password. Google Drive access requires OAuth.
Recommended: use the built-in OAuth flow so you do not have to paste access tokens.

### Google Cloud setup (OAuth)
1) Enable the Google Drive API:
   https://console.cloud.google.com/apis/library/drive.googleapis.com
2) Configure the OAuth consent screen:
   https://console.cloud.google.com/apis/credentials/consent
   - If the consent screen is in Testing, add your Google account as a Test user.
3) Create OAuth credentials (Web application is recommended):
   https://console.cloud.google.com/apis/credentials
   - Authorized redirect URI: `http://localhost:8080/`

### Local .env setup
Copy the example file and add your values:
```bash
cp .env.example .env
```
Fill in:
```
OAUTH_CLIENT_ID=...
OAUTH_CLIENT_SECRET=...
FOLDER_ID=...
GOOGLE_DRIVE_ACCESS_TOKEN=...   # optional fallback
SQLITE_PATH=./app.db            # optional override
```
The `.env` file is ignored by git.

### Manual OAuth code flow (no localhost callback)
If `http://localhost:8080/` is not reachable (for example when running in WSL or a remote VM):
1) Click **Sign in with Google** to generate the authorization link.
2) Complete consent and copy the redirect URL (or the `code=` value).
3) Paste the redirect URL in **Redirect URL** and click **Extract token**.

## Using the UI (Step-by-step)
1) Enter OAuth Client ID and Secret (auto-filled from `.env` if present).
2) Click **Sign in with Google** and authorize.
3) Enter **Folder ID or URL** (auto-filled from `.env` if present).
4) Click **List Files** to create a job and load files.
5) Update file names in **Manual Rename Editor** (blank means no change).
6) Click **Preview** to see the rename plan.
7) Click **Apply Rename** to rename files in Drive.
8) Click **Undo Rename** to revert the last rename batch.
9) Click **Preview Report** to generate the report text.
10) Click **Write Report to Folder** to upload the report.

Note: extraction fields remain placeholders (`<<<PENDING_EXTRACTION>>>`) until later increments.

## Development Notes
- If you do not have `uv` installed, see https://github.com/astral-sh/uv.
- Dependencies are defined in `pyproject.toml`.

## Notes
- Increment 1 only: no OCR, labels, or report generation.
- The Drive adapter returns all files in the folder.
