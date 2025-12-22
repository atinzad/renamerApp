# Google Drive Image Renamer (Increment 1)

This project provides the Increment 1 foundation for renaming images in a Google
Drive folder. It includes domain logic, ports, adapters (Google Drive + SQLite),
and a minimal Streamlit UI for manual rename preview, apply, and undo.

Increment 1 scope:
- Create jobs and list image files from a folder
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

2) Start the Streamlit UI:
```bash
streamlit run src/app/ui_streamlit/main.py
```

3) In the UI, enter:
- Access Token (Google Drive API v3 bearer token)
- Folder ID (Drive folder to scan)
- SQLite Path (defaults to `./app.db`)

Then use:
- Create Job — loads image files into the job
- Preview — shows the rename plan
- Apply Rename — renames files and saves undo
- Undo Last — reverts the last rename batch

## Development Notes
- If you do not have `uv` installed, see https://github.com/astral-sh/uv.
- Dependencies are defined in `pyproject.toml`.

## Notes
- Increment 1 only: no OCR, labels, or report generation.
- The Drive adapter only returns `image/*` files.
