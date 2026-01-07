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
  - Pass schema + OCR text to LLMPort for structured output.
- Layer E (Adapters) must remain dumb:
  - Adapters accept schema + text and return structured JSON output.
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
  - (LLMs are allowed only to interpret OCR text into labels/types/fields.)

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
- LLMPort (Increment 5)
- DrivePort.upload_text_file (Increment 2)
- DrivePort.download_file_bytes (Increment 3)

### 3.3 Composition root contract
- `app.container` MUST expose a function that builds services given runtime secrets/paths.
- UI must use this function only.

## 4. Increments Overview (Final Target)
- Increment 1: Manual rename + undo (Drive) + OAuth-based access token flow
- Increment 2: Per-file REPORT.txt generation (file list + extracted-content placeholders) + upload
- Increment 3: OCR for job files (and later example files)
- Increment 4: User-defined labels (“training”) + similarity-based classification
- Increment 5: LLM doc-type classification (fallback when no label match)
- Increment 6: Field extraction + deterministic name proposals (preview)
- Increment 7: Apply auto rename + report filled using consolidated fields + label inventory

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
- List files lists image/* files in folder
- Preview returns sanitized, collision-free names (including against unchanged files)
- Apply rename changes Drive file names accordingly
- Undo restores old names
- UI imports services only; no adapter imports

## 6. INCREMENT 2 SPEC — Per-file REPORT.txt (Files + Extracted Contents Placeholder)

### 6.1 Scope (MUST implement)
Generate a report file in the same Drive folder **based solely on**:
- what files exist in the job (using the names stored in `job_files.name`, which should reflect any applied renames), and
- the extracted contents for each file (for Increment 2 this is a placeholder).

MUST implement:
- Filename: `REPORT_YYYY-MM-DD.txt` (date = local job date)
- Deterministic rendering:
  - Files MUST be listed in a stable order: `(sort_index ASC, name ASC, file_id ASC)`
- For each file, render a **file block** that includes:
  - File name
  - Drive `file_id`
  - `mime_type`
  - `EXTRACTED_TEXT` placeholder (until Increment 3+)
  - `EXTRACTED_FIELDS_JSON` placeholder (until Increment 5+)
- User can preview report text in UI
- User can write report to Drive folder

### 6.2 Non-goals (MUST NOT implement)
- OCR or any extraction logic (Increment 3+)
- Labeling / “training” / similarity classification (Increment 4+)
- LLM-based doc type classification (Increment 5+)
- Consolidation into top-level identity fields (Name, Civil ID, etc.) (Increment 7)

### 6.3 Report format (canonical + deterministic)
The report MUST be plain text and use stable section headers exactly as follows.

**Header (minimal):**
- `REPORT_VERSION: 1`
- `JOB_ID: <job_id>`
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
  - `preview_report(job_id: str) -> str`
  - `write_report(job_id: str) -> str` (returns created report `file_id`)
- For Increment 2, the service MUST:
  - load `jobs` + `job_files` from SQLite
  - render the canonical report format above
  - fill `EXTRACTED_*` blocks with the placeholder token

### 6.6 Storage changes
- Storing the created report `file_id` is optional but recommended:
  - `ALTER jobs ADD COLUMN report_file_id TEXT`

### 6.7 UI requirements
- In job view:
  - Button: “Preview Report”
  - Show report text area
  - Button: “Write Report to Folder”

### 6.8 Acceptance criteria
- Report preview lists **all job files** in stable order
- Each file block contains the placeholder token for extracted content
- Report upload creates a text file in the Drive folder
- No OCR/LLM/labels are required for Increment 2


## 7. INCREMENT 3 SPEC — OCR for Job Files (Text Extraction)
### 7.1 Scope (MUST implement)
- Download each image file’s bytes from Drive
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

### 7.6 Storage changes (SQLite)
- Add table:
  - ocr_results(job_id TEXT, file_id TEXT, ocr_text TEXT, ocr_confidence REAL, updated_at TEXT)
- Add methods to StoragePort:
  - save_ocr_result(job_id, file_id, OCRResult)
  - get_ocr_result(job_id, file_id) -> OCRResult | None

### 7.7 UI requirements
- Button: “Run OCR”
- Per file: “View OCR” toggle/expand showing OCR text

### 7.8 Acceptance criteria
- OCR text stored for each processed file
- OCR can be rerun (overwrites prior result)
- App still supports manual rename/undo and report upload from previous increments

## 8. INCREMENT 4 SPEC — User Labels (“Training”) + Similarity-Based Classification
### 8.1 Scope (MUST implement)
- User can create, deactivate, and list labels
- User can attach one or more example documents (Drive file IDs) to a label
- For each example:
  - OCR text must be stored (reuse OCRPort)
  - A feature representation must be stored:
    - Preferred: embedding vector of OCR text
    - Fallback (if embeddings provider not configured): lexical fingerprint (token set)
- Classify job files by matching them against label examples
- Store per-file assigned label + confidence score
- UI shows label assignments and allows manual override
- Admin can define an extraction_schema (JSON object defining keys/types) and a naming_template
  for every label created

### 8.2 Non-goals (MUST NOT implement)
- LLM doc-type classification (Increment 5)
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
    - MATCH_THRESHOLD = 0.82
    - AMBIGUITY_MARGIN = 0.02
- If embeddings not available:
  - Lexical scoring fallback:
    - Normalize OCR text -> tokens
    - Score = Jaccard similarity with example token set
    - Use a lower threshold (e.g., 0.35)
  - Still return MATCHED/NO_MATCH/AMBIGUOUS

### 8.6 Services requirements
- LabelService
  - create_label(name) -> Label
  - deactivate_label(label_id) -> None
  - list_labels() -> list[Label]
  - attach_example(label_id, file_id) -> LabelExample
  - process_examples(label_id | None) -> None
    - OCR example files (if not already)
    - compute embedding/token fingerprint
    - save features
- LabelClassificationService
  - classify_job_files(job_id) -> None
  - requires OCR results for job files
  - for each file: compute embedding/tokens and match to label library
  - store assigned label + match score + status
  - override_file_label(job_id, file_id, label_id | None) -> None

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
  - label_example_features(example_id TEXT PRIMARY KEY, ocr_text TEXT, embedding_json TEXT, token_fingerprint TEXT, updated_at TEXT)
  - file_label_assignments(job_id TEXT, file_id TEXT, label_id TEXT, score REAL, status TEXT, updated_at TEXT)
  - file_label_overrides(job_id TEXT, file_id TEXT, label_id TEXT, updated_at TEXT)

### 8.8 UI requirements
- New “Labels” page:
  - Create label (text input)
  - List labels + deactivate
  - Attach example (Drive file_id input)
  - Show examples per label and whether processed
  - Button: “Process examples” (runs OCR + embeddings/tokens)
  - Validate extraction_schema and naming_template (via validate_schema_config) before saving label configuration
- Job page:
  - Button: “Classify using labels”
  - Column: Assigned Label, Score, Status (MATCHED/AMBIGUOUS/NO_MATCH)
  - Override dropdown: choose a label or clear

### 8.9 Acceptance criteria
- User can create label and attach examples
- Example processing stores features
- Classification assigns labels to job files deterministically using similarity
- Overrides persist and take precedence

### 8.10 Agent preset import/export (Seed mechanism)
- On startup, if no labels exist, check for `presets.json` in the repo root
- If present, auto-load label presets into storage
- Services layer orchestrates auto-seed during initialization
- StoragePort must support bulk insert for label presets
- Provide export capability to write current labels to `presets.json`

### 8.11 Domain requirements (schema validation)
- Domain must provide a validation function:
  - validate_schema_config(schema_json, naming_template) -> list[str] | None
  - validates schema_json is valid JSON
  - validates schema_json follows a flat key-value pair structure
  - ensures every placeholder in naming_template (e.g., {customer_name}) exists as a key in schema_json

### 8.12 No-code schema builder UI/UX
- Provide a dynamic list of rows where users enter:
  - Field Name
  - Data Type (String, Number, Date) via dropdown
- Advanced Mode toggle:
  - Switch to a Raw JSON Editor for power users
  - Changes are kept in sync between both views
- Serialization:
  - The UI converts the visual list into extraction_schema_json before calling the service layer
- UX helper:
  - Provide “Copy Placeholder” buttons for each field to assist in naming_template creation

## 9. INCREMENT 5 SPEC — LLM Doc-Type Classification (Fallback for Unlabeled Files)
### 9.1 Scope (MUST implement)
- For files with NO_MATCH (and not overridden):
  - Use an LLM to assign a generic doc type: CIVIL_ID, CONTRACT, INVOICE, OTHER
- Store doc type + confidence + signals
- Keep label classification as first priority:
  - If a file has a label MATCHED (or overridden), LLM doc-type classification is optional and may be skipped.

### 9.2 New port: LLMPort
- classify_doc_type(ocr_text: str) -> {doc_type: str, confidence: float, signals: list[str]}
- (No extraction yet; extraction comes Increment 6)

### 9.3 Domain models
- DocType enum
- DocTypeClassification(doc_type, confidence, signals)

### 9.4 Services requirements
- DocTypeClassificationService
  - classify_unlabeled_files(job_id) -> None
  - Determine unlabeled = no label assignment OR status=NO_MATCH and no override
  - Requires OCR text
  - Store doc type classification

### 9.5 Storage changes (SQLite)
- Add table:
  - doc_type_classifications(job_id TEXT, file_id TEXT, doc_type TEXT, confidence REAL, signals_json TEXT, updated_at TEXT)
  - doc_type_overrides(job_id TEXT, file_id TEXT, doc_type TEXT, updated_at TEXT) (optional)

### 9.6 UI requirements
- Job page:
  - Button: “Classify doc types (fallback)”
  - Column: Doc Type + confidence
  - Optional override selector

### 9.7 Acceptance criteria
- LLM classification runs only for unlabeled/unmatched files
- Results are stored and displayed
- Label results remain authoritative if present

## 10. INCREMENT 6 SPEC — Field Extraction + Deterministic Naming Proposals (Preview)
### 10.1 Scope (MUST implement)
- Use a single Dynamic Extractor Agent hydrated at runtime
- Extraction uses OCR text and a label-specific JSON schema to produce structured fields
- Deterministic naming proposals generated from extracted fields
- Preview table shows original -> proposed + warnings (missing fields, low confidence)
- No automatic rename apply is required in this increment (apply happens Increment 7), but it may be included as a separate button if desired.

### 10.2 Key design decision: extractor hydration priority
For each file:
1) If file has an assigned label (or override), hydrate the extractor with that label’s schema
2) Else if file has doc_type classification, use a doc-type default schema
3) Else use a generic schema that produces minimal fields

### 10.3 Domain requirements
- Extraction field models are dynamic based on label-defined schema
  - Schema is a JSON object describing keys and types
  - Each extracted field may include confidence (0..1) or “unknown”
- Naming templates:
  - Deterministic template rules per label (naming_template)
  - Templates are filled based on extracted keys; missing keys resolve to UNKNOWN
- Missing field handling:
  - If required field missing -> include placeholder "UNKNOWN"
  - Or mark as “needs review” and do not generate final name unless allowed by policy
- Naming sanitization and collisions reuse Increment 1 logic

### 10.4 Port requirements
- LLMPort MUST add a generic “extract_fields” method:
  - extract_fields(schema: dict, ocr_text: str) -> dict
- LLMAdapter MUST use structured output (JSON mode) to satisfy the provided schema
- StoragePort methods to store extraction results

### 10.5 Services requirements
- ExtractionService
  - extract_fields_for_job(job_id) -> None
  - Fetch label schema from storage and hydrate the extractor per file
  - Pass schema + OCR text to LLMPort for structured output
  - Store extraction results
- NamingProposalService
  - preview_naming(job_id) -> list[RenameOp] + warnings
  - Build proposed filenames deterministically using label naming_template
  - Resolve collisions against folder existing names

### 10.6 Storage changes (SQLite)
- Add tables:
  - label_extractor_config(label_id TEXT PRIMARY KEY, naming_template TEXT, updated_at TEXT)
  - extractions(job_id TEXT, file_id TEXT, schema_json TEXT, fields_json TEXT, confidences_json TEXT, updated_at TEXT)
  - naming_previews(job_id TEXT, file_id TEXT, proposed_name TEXT, warnings_json TEXT, updated_at TEXT) (optional cache)

### 10.7 UI requirements
- Labels page:
  - For each label: define extraction_schema (JSON) and naming_template
- Job page:
  - Button: “Extract fields”
  - Button: “Preview auto names”
  - Table: original name, proposed name, warnings
  - For each file: show extracted fields (expandable)

### 10.8 Acceptance criteria
- At least one extractor works end-to-end
- Deterministic naming proposals are generated
- Warnings are produced for missing/uncertain fields
- No rename is performed without explicit apply step (Increment 7)

## 11. INCREMENT 7 SPEC — Apply Auto Rename + Report Filled via Consolidation
### 11.1 Scope (MUST implement)
- Apply the naming proposal (rename files in Drive)
- Undo remains supported
- Generate a final REPORT.txt that is populated from extracted fields
- Report inventory includes counts per label and per doc type

### 11.2 Consolidation rules (deterministic)
- Consolidation is dynamic across all extracted keys:
  - Collect all unique keys found across all extracted documents in a job
  - For each key, aggregate candidates from extraction outputs across files
  - Score candidates by confidence and frequency across files
  - Choose best candidate if score clearly highest
  - If multiple strong candidates -> “MULTIPLE” and list in Notes
  - If no candidates -> “UNKNOWN"

### 11.3 Services requirements
- RenameService.apply_rename reused:
  - Must save undo log first
  - Must rename in stable order
- ConsolidationService
  - consolidate_report_fields(job_id) -> report_fields + notes
- ReportService updated
  - preview_report uses consolidated values
  - write_report writes final report

### 11.4 Storage changes
- Add table:
  - consolidation_results(job_id TEXT PRIMARY KEY, report_fields_json TEXT, notes_json TEXT, updated_at TEXT)
- Persist final applied rename plan (optional but recommended):
  - applied_renames(job_id TEXT, file_id TEXT, old_name TEXT, new_name TEXT, applied_at TEXT)

### 11.5 UI requirements
- Job page:
  - Button: “Apply auto rename”
  - Button: “Preview final report”
  - Button: “Write final report”
  - Show summary: number renamed, number skipped, number needs review

### 11.6 Acceptance criteria
- Files renamed according to previewed plan
- Undo restores originals
- Report is filled with consolidated values, stable schema, and includes label inventory
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
