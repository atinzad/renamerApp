# Google Drive Image Renamer

Rename files in a Google Drive folder with a Streamlit UI. Preview changes, apply
renames, undo the last rename, run OCR (images + PDFs), classify files with local
labels stored in SQLite, generate/upload a per-file report, and auto-run LLM
fallback classification when similarity is below threshold. Labels also support
per-label extraction schema + instructions and LLM-backed field extraction (Increment 6).

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

2) Install system OCR dependencies (Ubuntu):
```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-ara poppler-utils
```

3) Activate the virtual environment:
```bash
source .venv/bin/activate
```

4) Start the Streamlit UI:
```bash
PYTHONPATH=src streamlit run src/app/ui_streamlit/main.py
```

Optional (LLM fallback):
- Set `LLM_PROVIDER=openai`
- Set `OPENAI_API_KEY=...`
- Optionally set `OPENAI_MODEL` and `LLM_LABEL_MIN_CONFIDENCE`

Increment 6 (Field Extraction):
- Set `LLM_PROVIDER=openai`
- Set `OPENAI_API_KEY=...`
- In Labels view, generate schema + instructions from examples or edit them directly
- Run OCR, then click **Extract fields** in the Job actions or per-file controls.

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
TEST_SQLITE_PATH=./app.db       # optional override for scripts
LLM_PROVIDER=openai             # optional (LLM fallback)
OPENAI_API_KEY=...              # optional (LLM fallback)
OPENAI_MODEL=...                # optional (LLM fallback)
LLM_LABEL_MIN_CONFIDENCE=0.75   # optional (LLM fallback)
MATCH_THRESHOLD=0.6             # embeddings similarity threshold
LEXICAL_MATCH_THRESHOLD=0.35    # token similarity threshold
AMBIGUITY_MARGIN=0.02           # margin to avoid ambiguous matches
EMBEDDINGS_PROVIDER=openai      # openai | dummy
EMBEDDINGS_MODEL=text-embedding-3-large # OpenAI embeddings model
EMBEDDINGS_LOCAL_MODEL=BAAI/bge-m3      # unused (local embeddings removed)
EMBEDDINGS_DEVICE=cpu           # unused (local embeddings removed)
```
The `.env` file is ignored by git.

### OCR Language
Set `OCR_LANG` to control Tesseract languages (default: `ara+eng`).
Examples:
```
OCR_LANG=eng
OCR_LANG=ara+eng
```
For PDFs, the app will attempt to use a text layer (via `pdfminer.six`) before
rasterizing pages for OCR. For scans/photos, OCR runs two passes (raw + preprocessed)
and merges the text for downstream LLM extraction.

### Classification thresholds
Classification uses embeddings when available, otherwise lexical token overlap.
Tune these in `.env`:
- `MATCH_THRESHOLD` — embeddings similarity required for MATCHED
- `LEXICAL_MATCH_THRESHOLD` — token overlap required for MATCHED
- `AMBIGUITY_MARGIN` — minimum gap between top-2 scores to avoid ambiguous matches

If a file is below threshold, the LLM fallback runs (when configured) and stores
its suggestion alongside the rule-based result.

### Local labels
Labels are stored in SQLite (`app.db`, gitignored). Each label keeps OCR text examples
from files you add via **Add as label example** or when creating a new label. Manage
labels and examples in the **Labels** view inside the Streamlit app.

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
5) Click **Run OCR** to process images and PDFs in the folder.
6) For each file:
   - Use **Create new label** to add a label (stores OCR example).
   - Or pick a label in **Classify** dropdown.
   - (Optional) **Add as label example** to attach OCR to a label.
7) Click **Classify files** to auto-assign labels using OCR similarity.
   - If similarity is below threshold, LLM fallback runs automatically (if configured).
9) In **Labels**, edit schema + instructions or generate them from OCR examples.
10) Click **Extract fields** (job-level or per-file) to populate extracted fields.
11) Rename fields auto-fill with `Label[_NN].ext` for MATCHED files; edit if needed.
12) Click **Preview** to see the rename plan.
13) Click **Apply Rename** to rename files in Drive.
14) Click **Undo Rename** to revert the last rename batch.
15) Click **Preview Report** to generate the report text.
16) Click **Write Report to Folder** to upload the report.

## Development Notes
- If you do not have `uv` installed, see https://github.com/astral-sh/uv.
- Dependencies are defined in `pyproject.toml`.

## Manual Verification Scripts
Run a live end-to-end check (Drive + OCR + report preview):
```bash
env PYTHONPATH=src uv run python scripts/verify_increment3.py
```
Run the Increment 4 label flow check (Drive + OCR + labels.json classification):
```bash
env PYTHONPATH=src uv run python scripts/verify_increment4.py
```
Run the Increment 5 LLM fallback check (Drive + OCR + LLM suggestion storage):
```bash
env PYTHONPATH=src uv run python scripts/verify_increment5.py
```
Run the Increment 6 extraction check (Drive + OCR + extraction storage):
```bash
env PYTHONPATH=src uv run python scripts/verify_increment6.py
```
Score LLM fallback per label (single-candidate scoring):
```bash
env PYTHONPATH=src uv run python scripts/score_labels_llm.py --ocr ocr_text.txt --sqlite ./app.db
```
Classify a local OCR text file (rule-based + LLM fallback):
```bash
env PYTHONPATH=src uv run python scripts/classify_ocr_text.py --ocr ocr_text.txt --sqlite ./app.db
```
Compare PDF OCR strategies (text layer, raw, preprocessed, merged):
```bash
env PYTHONPATH=src uv run python scripts/compare_pdf_ocr.py civ_id_example.pdf
```
Compare OCR strategies vs direct-image extraction (speed + usage):
```bash
env PYTHONPATH=src OCR_LANG=ara+eng uv run python scripts/compare_ocr_llm_extraction.py civ_id_example.pdf --label Civil_ID
```
Compare LLM fallback strategies (single-call vs per-label):
```bash
env PYTHONPATH=src uv run python scripts/compare_llm_fallback_strategies.py --ocr ocr_text.txt --db app.db
```

## Notes
- Labels are local and stored in SQLite (`app.db`, gitignored).
- LLM fallback suggestions are optional and do not override labels.
- Field extraction is implemented and stored per file.
- The Drive adapter skips `text/plain` files when listing a folder.
- Local embeddings are not included in this repo; use OpenAI embeddings or dummy.
