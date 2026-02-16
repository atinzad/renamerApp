# Specification Document — Incremental Build (Pure Python) — Google Drive Image Renamer + User-Label Training + Report

## 0. Purpose of This Document
0.1 This document defines a set of increments that build a working application step-by-step. Each increment MUST be:
- Fully functional end-to-end
- Backward compatible with the previous increment (no refactor required to proceed)
- Modular at file and class/function level so the UI can be replaced later

0.2 This document is intentionally detailed so that if it is given to an LLM, the LLM can:
- Generate tight prompts per increment
- Implement only what is required for that increment
- Preserve architecture and boundaries
- Produce a functioning app at the end of each increment

0.3 High-level product behavior
- Input: Google Drive folder containing images
- For each image:
  - (Later increments) OCR -> classification -> field extraction -> deterministic naming proposal
- Rename is applied only after preview + user approval

- Output (later increments):
  - Renamed images
  - A structured REPORT.txt in the folder, using a fixed schema with stable labels/order
- “Training” / labeling:
  - User can create labels and attach example documents
  - Future docs are classified into those labels using similarity to examples

## 1. Core Architectural Requirements (Non-negotiable)
### 1.1 Layering (must remain true in all increments)
- Layer A: UI (Streamlit initially; replaceable later)
- Layer B: Application Services (use-cases; orchestration only)
- Layer C: Domain (pure logic; no I/O)
- Layer D: Ports (interfaces/protocols)
- Layer E: Adapters (Google Drive, OCR, Embeddings, LLM, Storage)

### 1.1.1 Dynamic schema-driven agent hydration (must remain true)
- Layer B (Services) is responsible for agent hydration:
  - Fetch label-specific extraction_schema and naming_template from storage.
  - Pass schema + document input to LLMPort for structured output.
- Layer E (Adapters) must remain dumb:
  - Adapters accept schema + input context (text or image/PDF bytes) and return structured JSON output.
  - Adapters do not contain label-specific logic or hard-coded extractors.
- Single-file mandate for Streamlit UI remains intact (single entrypoint, no multi-page UI).

### 1.2 Import rules
- UI MUST import only from:
  - `app.container` (composition root)
  - `app.services.*`
  - `app.domain.*` (optional, for rendering)
- UI MUST NOT import `app.adapters.*`
- Domain MUST NOT import:
  - google SDKs
  - Streamlit
  - sqlite3 (or any database)
  - network clients
- Services MUST NOT implement low-level API calls. They call ports.

### 1.3 Determinism and safety rules
- Filename sanitization MUST be deterministic.
- Collision resolution MUST be deterministic.
- Applying rename MUST write an undo record BEFORE renaming any file.
- Undo MUST restore prior names.
- LLMs MUST NEVER directly rename files or produce final report formatting.
  - (LLMs are allowed only to interpret OCR text and/or source document content into labels/types/fields.)

### 1.4 Configuration
- All runtime configuration MUST be in `app.settings` (environment variables + defaults).
- A single composition root `app.container` MUST build service objects by injecting adapters.

## 2. Baseline Repository Structure (Stable Across Increments)
### 2.1 Root structure
```
repo/
  pyproject.toml
  README.txt
  .env.example
  src/
    app/
      __init__.py
      settings.py
      container.py
      domain/
      ports/
      adapters/
      services/
      ui_streamlit/
        __init__.py
        main.py
        pages/
        components/
```

### 2.2 Module responsibilities (stable)
- `app/domain`: dataclasses + pure functions (sanitize, collisions, report rendering, consolidation)
- `app/ports`: Protocols for external dependencies
- `app/adapters`: Concrete implementations of ports
- `app/services`: Use-cases coordinating domain + ports
- `ui_streamlit`: UI that calls services only

## 3. Cross-Increment Contracts (Stable Interfaces and Models)
### 3.1 Domain models (initial set, added over time)
- FileRef(file_id: str, name: str, mime_type: str)
- Job(job_id: str, folder_id: str, created_at: datetime, status: str)
- RenameOp(file_id: str, old_name: str, new_name: str)
- UndoLog(job_id: str, created_at: datetime, ops: list[RenameOp])

### 3.2 Port contracts (minimum stable set; methods added by increments)
#### 3.2.1 DrivePort (Increment 1 baseline)
- list_folder_files(folder_id: str) -> list[FileRef]
- rename_file(file_id: str, new_name: str) -> None

#### 3.2.2 StoragePort (Increment 1 baseline)
- create_job(folder_id: str) -> Job
- get_job(job_id: str) -> Job | None
- save_job_files(job_id: str, files: list[FileRef]) -> None
- get_job_files(job_id: str) -> list[FileRef]
- save_undo_log(undo: UndoLog) -> None
- get_last_undo_log(job_id: str) -> UndoLog | None
- clear_last_undo_log(job_id: str) -> None
- bulk_insert_label_presets(labels: list[dict]) -> None

#### 3.2.3 Ports added later
- OCRPort (Increment 3)
- EmbeddingsPort + label storage methods (Increment 4)
- LLMPort (Increment 5, label-name fallback)
- DrivePort.upload_text_file (Increment 2)
- DrivePort.download_file_bytes (Increment 3)

### 3.3 Composition root contract
- `app.container` MUST expose a function that builds services given runtime secrets/paths.
- UI must use this function only.

## 4. Increments Overview (Final Target)
- Increment 1: Manual rename + undo (Drive) + OAuth-based access token flow
- Increment 2: REPORT.txt generation for latest job (file list + extracted-content placeholders) + upload
- Increment 3: OCR for job files (and later example files)
- Increment 4: User-defined labels (“training”) + similarity-based classification (SQLite-backed)
- Increment 5: LLM label-name fallback (suggestion layer when no label match)
- Increment 6: Field extraction for reporting and decision support
- Increment 7: Report filled using consolidated fields + label inventory (rename remains manual/label-based)

## 5. INCREMENT 1 SPEC — Manual Rename + Undo (Drive integration)
### 5.1 Scope (MUST implement)
- User can input Google access token (manual fallback)
- User can input OAuth Client ID and Client Secret to generate an access token via OAuth
- User can paste the OAuth redirect URL and extract the code to obtain an access token
- User can input a Drive folder ID or full folder URL
- App lists image files in that folder
- User manually enters new names per file (subset allowed)
- App previews a rename plan:
  - Sanitization applied
  - Collisions resolved deterministically
  - Collisions include conflicts with:
    - other proposed names
    - existing filenames in the folder that are NOT being renamed
- User applies rename
- Undo last rename for that job

### 5.2 Non-goals (MUST NOT implement)
- OCR
- Labels / training
- LLM classification/extraction
- Report generation
- Background workers
- Drive Picker UI (folder picker). Folder ID text input is acceptable.

### 5.3 UI requirements (Streamlit, minimal)
- Inputs:
  - OAuth Client ID
  - OAuth Client Secret
  - Sign in with Google button (generates authorization link)
  - Redirect URL input + “Extract token” button
  - Access token (manual fallback; auto-filled when OAuth succeeds)
  - Folder ID or full folder URL
  - SQLite path (default `./app.db`)
- Buttons:
  - List Files
  - Preview
  - Apply Rename
  - Undo Rename
- Display:
  - job_id + file list (file name, file_id)
- Manual rename editor:
  - For each file: input box for new filename (blank means no change)

### 5.4 Domain requirements
- sanitize_filename(name: str) -> str
  - Remove invalid characters for common filesystems: `/ \ : * ? " < > |` and control chars
  - Normalize whitespace (collapse multiple spaces)
  - Trim ends
  - Must not return empty string; if empty -> `"UNNAMED"`
- resolve_collisions(ops: list[RenameOp], existing_names: set[str]) -> list[RenameOp]
  - Append suffix `_01`, `_02`, ... before extension
  - Must be deterministic (input order)
  - Ensure final new_name not in:
    - other final new_names
    - existing_names of unchanged files
- build_manual_plan(files: list[FileRef], edits: dict[file_id -> desired_name]) -> list[RenameOp]
  - Create rename operations only for edited files

### 5.5 Services requirements
- JobsService
  - create_job(folder_id): creates job in storage, lists files from Drive, stores file list
  - list_files(job_id): returns stored list
- RenameService
  - preview_manual_rename(job_id, edits):
    - loads stored job files
    - builds ops
    - applies sanitization + collision resolution (requires existing_names)
    - returns final ops
  - apply_rename(job_id, ops):
    - save undo log BEFORE any rename call
    - apply Drive renames in stable order
  - undo_last(job_id):
    - load undo log
    - rename back in reverse order
    - clear undo log after successful undo

### 5.6 Storage schema (SQLite) — DDL MUST be included in implementation
- jobs(job_id TEXT PRIMARY KEY, folder_id TEXT, created_at TEXT, status TEXT)
- job_files(job_id TEXT, file_id TEXT, name TEXT, mime_type TEXT, sort_index INTEGER)
- undo_logs(job_id TEXT PRIMARY KEY, created_at TEXT)
- undo_ops(job_id TEXT, file_id TEXT, old_name TEXT, new_name TEXT, op_index INTEGER)
Notes:
- One undo log per job (overwrite on new apply)
- job_files replaced when create_job called again for same job_id (normally not needed)

### 5.7 Acceptance criteria / definition of done
- List files includes only `image/*` and `application/pdf` files; skips folders and other mime types (including `text/plain`)
- Preview returns sanitized, collision-free names (including against unchanged files)
- Apply rename changes Drive file names accordingly
- Undo restores old names
- UI imports services only; no adapter imports

## 6. INCREMENT 2 SPEC — REPORT.txt for Latest Job (Files + Extracted Contents Placeholder)

### 6.1 Scope (MUST implement)
Generate a report file in the same Drive folder **based solely on the latest job**:
- what files exist in the latest job (using the names stored in `job_files.name`, which should reflect any applied renames), and
- the extracted contents for each file (for Increment 2 this is a placeholder unless data already exists).

Evolved Increment 2 behavior:
- Report rendering MUST be driven by a structured report model (not ad-hoc string concatenation).
- If OCR text or extracted fields already exist, the report SHOULD include them; otherwise placeholders remain.

MUST implement:
- Filename: `REPORT_YYYY-MM-DD.txt` (date = local job date)
- Deterministic rendering:
  - Files MUST be listed in a stable order: `(sort_index ASC, name ASC, file_id ASC)`
- For each file, render a **file block** that includes:
  - File name
  - Drive `file_id`
  - `mime_type`
  - `EXTRACTED_TEXT` placeholder (until Increment 3+)
  - `EXTRACTED_FIELDS_JSON` placeholder (until Increment 6+)
- User can preview report text in UI (latest job only)
- User can write report to Drive folder (latest job only)

### 6.2 Non-goals (MUST NOT implement)
- OCR or any extraction logic (Increment 3+)
- Labeling / “training” / similarity classification (Increment 4+)
- LLM-based label fallback (Increment 5+)
- Consolidation into top-level identity fields (Name, Civil ID, etc.) (Increment 7)

### 6.3 Report format (canonical + deterministic)
The report MUST be plain text and use stable section headers exactly as follows.

**Header (minimal):**
- `REPORT_VERSION: 1`
- `JOB_ID: <job_id>` (latest job only)
- `FOLDER_ID: <folder_id>`
- `GENERATED_AT: <ISO-8601 local datetime>`

**Files section:**
For each file, render:

```
--- FILE START ---
INDEX: <1-based index in stable order>
FILE_NAME: <job_files.name>
FILE_ID: <file_id>
MIME_TYPE: <mime_type>

EXTRACTED_TEXT:
<<<PENDING_EXTRACTION>>>

EXTRACTED_FIELDS_JSON:
<<<PENDING_EXTRACTION>>>
--- FILE END ---
```

Notes:
- The placeholder token MUST be exactly `<<<PENDING_EXTRACTION>>>` (verbatim).
- No additional “summary fields” are required in Increment 2 (counts, “Needs Review”, etc.).
- Future increments may replace the placeholder blocks with actual extraction outputs, but the headers MUST remain stable.

### 6.4 Ports requirements
- DrivePort MUST add:
  - `upload_text_file(folder_id: str, filename: str, content: str) -> str` (returns created `file_id`)

### 6.5 Services requirements
- ReportService
  - `preview_report(job_id: str | None = None) -> str`
  - `write_report(job_id: str | None = None) -> str` (returns created report `file_id`)
- For Increment 2, the service MUST:
  - load `jobs` + `job_files` from SQLite
  - resolve latest job if `job_id` is None (by `jobs.created_at` DESC)
  - render the canonical report format above
  - fill `EXTRACTED_*` blocks with the placeholder token if no stored data exists

### 6.6 Storage changes
- Storing the created report `file_id` is optional but recommended:
  - `ALTER jobs ADD COLUMN report_file_id TEXT`

### 6.7 UI requirements
- In job view:
  - Button: “Preview Report”
  - Show report text area
  - Button: “Write Report to Folder”

### 6.8 Acceptance criteria
- Report preview lists **latest job files** in stable order
- Each file block contains the placeholder token for extracted content when no stored data exists
- Report upload creates a text file in the Drive folder
- No OCR/LLM/labels are required for Increment 2


## 7. INCREMENT 3 SPEC — OCR for Job Files (Text Extraction)
### 7.1 Scope (MUST implement)
- Download each image/PDF file’s bytes from Drive
- Run OCR to extract text
- Store OCR text per file in storage
- UI can display OCR text per file

### 7.2 Non-goals (MUST NOT implement)
- Labels/LLM classification
- Auto renaming based on OCR
- Background queues (allowed later; for now synchronous is OK)

### 7.3 Port changes
- DrivePort MUST add:
  - download_file_bytes(file_id: str) -> bytes
- OCRPort MUST be introduced:
  - extract_text(image_bytes: bytes) -> OCRResult

### 7.4 Domain models
- OCRResult(text: str, confidence: float | None)

### 7.5 Services requirements
- OCRService
  - run_ocr(job_id: str, file_ids: list[str] | None = None) -> None
  - For each file:
    - download bytes
    - call OCRPort.extract_text
    - save OCRResult to storage
  - OCR targets:
    - `image/*` and `application/pdf` files
    - skip `text/plain` files entirely
  - Batch OCR skips files that already have OCR stored (unless file_ids is provided)

### 7.6 Storage changes (SQLite)
- Add table:
  - ocr_results(file_id TEXT PRIMARY KEY, ocr_text TEXT, ocr_confidence REAL, updated_at TEXT)
- Add methods to StoragePort:
  - save_ocr_result(job_id, file_id, OCRResult)
  - get_ocr_result(job_id, file_id) -> OCRResult | None
Notes:
- OCR is stored per `file_id` only (not per job), and is reused across jobs.

### 7.7 UI requirements
- Button: “Run OCR”
- Per file: “View OCR” toggle/expand showing OCR text
  - View OCR appears after OCR completes for the active job

### 7.8 Acceptance criteria
- OCR text stored for each processed file
- OCR can be rerun (overwrites prior result)
- App still supports manual rename/undo and report upload from previous increments
 - Report EXTRACTED_TEXT uses stored OCR text when available; otherwise placeholder

### 7.9 OCR dependencies (implementation guidance)
- Python deps: `pytesseract`, `pillow`, `pdf2image`
- System deps (Ubuntu): `tesseract-ocr`, `tesseract-ocr-ara`, `poppler-utils`
- OCR workers default to CPU core count at runtime (auto-detected)

## 8. INCREMENT 4 SPEC — User Labels (“Training”) + Similarity-Based Classification
### 8.1 Scope (MUST implement)
- User can create labels inline per job file
- Labels are stored in SQLite (local `app.db`, gitignored)
- Each label stores OCR text examples from files assigned to that label
- Classify job files by matching OCR text against label examples (lexical similarity)
- Store per-file classification results in UI state (label name, score, status)
- Rename field auto-fills from label name with numbering + original extension

### 8.2 Non-goals (MUST NOT implement)
- LLM label fallback (Increment 5)
- Automatic field extraction and naming (Increment 6+)

### 8.3 New domain models
- Label(
  label_id: str,
  name: str,
  is_active: bool,
  created_at: datetime,
  extraction_schema_json: str,
  naming_template: str,
  )
- LabelExample(example_id: str, label_id: str, file_id: str, filename: str, created_at: datetime)
- LabelMatch(label_id: str | None, score: float, rationale: str, status: one of {MATCHED, AMBIGUOUS, NO_MATCH})
  - Manual overrides via UI dropdown persist to storage and take priority in final report resolution

### 8.4 New port: EmbeddingsPort (recommended)
- embed_text(text: str) -> list[float]

### 8.5 Similarity algorithm requirements
- If embeddings available:
  - Compute cosine similarity between candidate embedding and each example embedding
  - Label score = max similarity across that label’s examples
  - Threshold policy:
    - If best score >= MATCH_THRESHOLD -> MATCHED
    - Else -> NO_MATCH
    - If multiple labels exceed threshold and (best - second_best) < AMBIGUITY_MARGIN -> AMBIGUOUS
  - Defaults (configurable in settings):
    - MATCH_THRESHOLD = 0.6
    - AMBIGUITY_MARGIN = 0.02
- If embeddings not available:
  - Lexical scoring fallback:
    - Normalize OCR text -> tokens
    - Score = Jaccard similarity with example token set
    - Use a lower threshold (e.g., 0.35)
  - Still return MATCHED/NO_MATCH/AMBIGUOUS

### 8.6 Services requirements
- Classification uses OCR text + label examples stored in SQLite
- Embeddings-based classification and label storage services remain optional for later increments

### 8.7 Storage changes (SQLite)
- Add tables:
  - labels(
    label_id TEXT PRIMARY KEY,
    name TEXT,
    is_active INTEGER,
    created_at TEXT,
    extraction_schema_json TEXT,
    naming_template TEXT
    )
  - label_examples(example_id TEXT PRIMARY KEY, label_id TEXT, file_id TEXT, filename TEXT, created_at TEXT)
    - file_id must be unique (a file may be attached to only one label)
  - label_example_features(example_id TEXT PRIMARY KEY, ocr_text TEXT, embedding_json TEXT, token_fingerprint TEXT, updated_at TEXT)
  - file_label_assignments(job_id TEXT, file_id TEXT, label_id TEXT, score REAL, status TEXT, updated_at TEXT)
  - file_label_overrides(job_id TEXT, file_id TEXT, label_id TEXT, updated_at TEXT)

### 8.8 UI requirements
- Job screen:
  - Per file: “Create new label” input + button (adds OCR example to SQLite)
  - Per file: “Classify” dropdown sourced from stored labels
    - Manual selection persists an override (stored in file_label_overrides)
  - Rename field auto-fills with label name + numbering + extension
  - Button: “Classify files” (runs lexical similarity over OCR text)
- Labels view (in the same Streamlit app):
  - View existing labels and examples
  - Add/delete label examples

### 8.9 Acceptance criteria
- User can create labels from job files and persist them in SQLite (`app.db`)
- Classification assigns labels deterministically using OCR text similarity
- Rename field auto-fills from label name when classification succeeds

### 8.10 Label storage (current)
- Labels and examples are stored in SQLite (`app.db`, gitignored)

### 8.11 Deferred schema configuration
- extraction_schema and naming_template collection is deferred to a later increment

## 9. INCREMENT 5 SPEC — LLM Label-Name Fallback (Suggestion Layer)
### 9.1 Scope (MUST implement)
- For files with NO_MATCH (and not overridden):
  - Use an LLM to suggest a label name from the configured fallback candidates
- Store label_name + confidence + signals
- Keep label classification as first priority:
  - If a file has a label MATCHED (or overridden), LLM fallback is optional and may be skipped.

### 9.2 New port: LLMPort
- classify_label(ocr_text: str, candidates: list[{name: str, instructions: str}]) -> {label_name: str | null, confidence: float, signals: list[str]}
- (No extraction yet; extraction comes Increment 6)

### 9.3 Domain models
- LabelFallbackCandidate(name, instructions)
- LabelFallbackClassification(label_name, confidence, signals)

### 9.4 Services requirements
- LLMFallbackLabelService
  - classify_unlabeled_files(job_id) -> None
  - Determine unlabeled = no label assignment OR status=NO_MATCH and no override
  - Requires OCR text
  - Candidates = labels where `llm` is non-empty (after strip)
  - Score candidates in a single LLM call with all labels; choose highest confidence
  - If highest confidence < min threshold, abstain
  - Store LLM label classification (label_name or null) with confidence + signals

### 9.5 Storage changes (SQLite)
- Add table:
  - llm_label_classifications(job_id TEXT, file_id TEXT, label_name TEXT NULL, confidence REAL, signals_json TEXT, updated_at TEXT)
  - llm_label_overrides(job_id TEXT, file_id TEXT, label_name TEXT, updated_at TEXT) (optional)

### 9.6 UI requirements
- Job page:
  - No separate button; LLM fallback runs automatically when similarity is below threshold
  - Column: LLM suggestion + confidence
  - Optional override selector

### 9.7 Acceptance criteria
- LLM classification runs only for unlabeled/unmatched files
- Results are stored and displayed
- Label results remain authoritative if present

## 10. INCREMENT 6 SPEC — Field Extraction (Reporting + Decision Support)
### 10.1 Scope (MUST implement)
- Use a single Dynamic Extractor Agent hydrated at runtime
- Extraction uses source image/PDF content, label-specific JSON schema, and label-specific instructions to produce structured fields
- Extracted fields are stored and rendered into the report for downstream review/decision making
- No filename proposal logic in this increment

### 10.2 Key design decision: extractor hydration priority
For each file:
1) If file has an assigned label (or override), hydrate the extractor with that label’s schema
2) Else use a generic schema that produces minimal fields

### 10.3 Domain requirements
- Extraction field models are dynamic based on label-defined schema
  - Schema is a JSON object describing keys and types
  - Each extracted field may include confidence (0..1) or “unknown”
- Missing field handling:
  - If required field missing -> include placeholder "UNKNOWN"
  - Or mark as “needs review” in extracted fields
- Example-driven schema builder:
  - User provides OCR examples and optional schema guidance for a label
  - If optional guidance is present, guidance takes precedence for schema generation
  - Otherwise system generates extraction_schema_json + extraction_instructions from OCR context with relevance filtering

### 10.4 Port requirements
- LLMPort MUST add a generic “extract_fields” method:
  - extract_fields(schema: dict, ocr_text: str, instructions: str | None = None) -> dict
- LLMPort MUST add image/PDF extraction:
  - extract_fields_from_image(schema: dict, file_bytes: bytes, mime_type: str, instructions: str | None = None) -> dict
- LLMAdapter MUST use structured output (JSON mode) to satisfy the provided schema
- StoragePort methods to store extraction results
- StoragePort MUST support label extraction instructions

### 10.5 Services requirements
- ExtractionService
  - extract_fields_for_job(job_id) -> None
  - Fetch label schema + extraction instructions from storage and hydrate the extractor per file
  - Pass schema + source image/PDF bytes + instructions to LLMPort for structured output
  - Store extraction results
  - No naming proposal service in this increment
- SchemaBuilderService
  - build_from_ocr(label_id, ocr_text) -> (schema, instructions)
  - Guidance-first behavior: if optional guidance is provided, schema generation uses guidance as the source of truth
  - Persists extraction_schema_json and extraction_instructions

### 10.6 Storage changes (SQLite)
- Add tables:
  - extractions(job_id TEXT, file_id TEXT, schema_json TEXT, fields_json TEXT, confidences_json TEXT, updated_at TEXT)

### 10.7 UI requirements
- Labels page:
  - For each label: define extraction_schema (JSON)
  - For each label: define extraction_instructions (text)
  - “Build schema from OCR example” action that generates schema + instructions
    - Optional schema guidance takes precedence over OCR when provided
    - Schema generation uses an LLM with a refinement pass
    - Cap schemas at 15 fields; use concise English snake_case keys
    - Arrays only when explicitly justified (plural list fields); otherwise strings
- Job page:
  - Button: “Extract fields”
  - For each file: show extracted fields (expandable)
  - Extraction uses source image/PDF input (OCR remains for classification)

### 10.8 Acceptance criteria
- At least one extractor works end-to-end
- Extracted fields are stored and visible in the report/UI
- Warnings are produced for missing/uncertain fields
- Labels support extraction instructions and guidance-first/OCR-fallback schema generation

## 11. INCREMENT 7 SPEC — Final Report (Latest Job Only)
### 11.1 Scope (MUST implement)
- Generate a final REPORT.txt for the **latest job only** with a human-readable, deterministic format
- Report includes, per file:
  - final filename (post-rename)
  - final classification (label)
  - extracted fields (pretty-printed, not JSON)
- Report must be easy to scan and visually clean (consistent spacing and headings)

### 11.2 Report format (deterministic, human-readable)
The report MUST be plain text and use stable section headers exactly as follows.

**Header (minimal):**
- `REPORT_VERSION: 2`
- `JOB_ID: <job_id>` (latest job only)
- `FOLDER_ID: <folder_id>`
- `GENERATED_AT: <ISO-8601 local datetime>`

**Files section (stable order):**
Order files by `(sort_index ASC, final_name ASC, file_id ASC)`.

For each file, render:
```
--- FILE START ---
INDEX: <1-based index in stable order>
FINAL_NAME: <final filename>
FILE_ID: <file_id>
FINAL_LABEL: <label name or UNLABELED>

EXTRACTED_FIELDS:
<pretty-printed fields, one per line: KEY: VALUE>
--- FILE END ---
```

Notes:
- `FINAL_NAME` uses applied rename if present; otherwise use current stored `job_files.name`.
- `FINAL_LABEL` resolution order:
  1) explicit user override (if any)
  2) stored label assignment (MATCHED/AMBIGUOUS/NO_MATCH)
  3) LLM fallback label suggestion (if configured and present)
  4) `UNLABELED`
- `EXTRACTED_FIELDS` must omit JSON syntax:
  - Render keys in deterministic order (schema order if available; otherwise alphabetical)
  - Arrays render as comma-separated values on one line
  - Missing fields render as `UNKNOWN`
- Do NOT include OCR text in the report.
- Include per-file timings (if available):
  - `TIMINGS_MS` section with `ocr_ms`, `classify_ms`, `extract_ms` (UNKNOWN if missing)

### 11.3 Services requirements
- ReportService updated
  - preview_report uses final per-file values for latest job
  - write_report writes final report for latest job
  - resolve latest job if `job_id` is None (by `jobs.created_at` DESC)

### 11.4 Storage changes
- Persist final applied rename plan (optional but recommended):
  - applied_renames(job_id TEXT, file_id TEXT, old_name TEXT, new_name TEXT, applied_at TEXT)
- Persist per-file timings (optional but recommended):
  - file_timings(job_id TEXT, file_id TEXT, ocr_ms INTEGER, classify_ms INTEGER, extract_ms INTEGER, updated_at TEXT)

### 11.5 UI requirements
- Job page:
  - Button: “Preview final report”
  - Button: “Write final report”
  - Show summary: number renamed, number skipped, number needs review

### 11.6 Acceptance criteria
- Report includes only final name, final label, and extracted fields for the latest job
- Report is deterministic, easy to scan, and excludes OCR text
- Fresh deployment can auto-load agent presets from `presets.json`
- Broken naming templates are rejected by schema validation before save
- Non-technical users can define new document types via the no-code schema builder without writing JSON

## 12. Prompt-Generation Guidance (for an LLM using this spec)
### 12.1 Per increment, prompts SHOULD be broken into silos:
- Domain-only prompt (pure logic)
- Ports-only prompt (Protocol interfaces)
- Adapter prompts (Drive/SQLite/OCR/Embeddings/LLM), one per adapter
- Services-only prompt (use-cases)
- UI-only prompt (Streamlit)
- “Definition of done checklist” prompt

### 12.2 Prompts MUST enforce scope
- Each prompt MUST instruct “do not implement beyond this increment”
- Each prompt MUST specify exact file paths to create/modify
- Each prompt MUST specify method signatures and responsibilities exactly
- Each prompt MUST preserve prior increment behavior

### 12.3 Prompts SHOULD request:
- Minimal runnable code
- Clear exceptions for expected failures (auth, missing folder, API error)
- A short run guide in README.txt

## 13. Security and Operational Notes (applies to all increments)
### 13.1 OAuth approach for MVP
- Streamlit UI may accept access_token pasted by user (fastest MVP)
- OAuth client flow may be used to generate access tokens
- Production OAuth flow is out of scope for these increments

### 13.2 Data stored
- SQLite stores job metadata, file IDs/names, undo logs
- Later increments store OCR text and embeddings:
  - Must be documented as sensitive data
  - Provide a simple “Delete job data” option later (optional)

### 13.3 Drive behavior
- Google Drive permits duplicate filenames in a folder.
- The app chooses to avoid duplicates via collision resolution to reduce confusion.
