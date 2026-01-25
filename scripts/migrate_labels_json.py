from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / ".env", override=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate labels.json into SQLite labels")
    parser.add_argument("--db", default="app.db", help="SQLite DB path")
    parser.add_argument(
        "--labels-json", default="labels.json", help="Path to labels.json"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Always insert examples even if label already has examples",
    )
    args = parser.parse_args()

    labels_path = Path(args.labels_json)
    if not labels_path.exists():
        raise SystemExit(f"labels.json not found at {labels_path}")
    data = json.loads(labels_path.read_text())
    if not isinstance(data, list):
        raise SystemExit("labels.json must be a list")

    conn = sqlite3.connect(args.db)
    try:
        _ensure_schema(conn)
        for label in data:
            name = str(label.get("name", "")).strip()
            if not name:
                continue
            llm = str(label.get("llm", "")).strip()
            examples = label.get("examples", []) or []
            label_id = _get_label_id(conn, name)
            if label_id is None:
                label_id = str(uuid4())
                conn.execute(
                    """
                    INSERT INTO labels(
                        label_id, name, is_active, created_at, extraction_schema_json,
                        naming_template, llm
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        label_id,
                        name,
                        1,
                        datetime.now(timezone.utc).isoformat(),
                        "{}",
                        "",
                        llm,
                    ),
                )
            else:
                if llm:
                    conn.execute(
                        "UPDATE labels SET llm = ? WHERE label_id = ?",
                        (llm, label_id),
                    )

            if not examples:
                continue
            if not args.force and _label_has_examples(conn, label_id):
                continue
            for example_text in examples:
                if not isinstance(example_text, str) or not example_text.strip():
                    continue
                example_id = str(uuid4())
                file_id = f"imported:{label_id}:{example_id}"
                conn.execute(
                    """
                    INSERT INTO label_examples(example_id, label_id, file_id, filename, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        example_id,
                        label_id,
                        file_id,
                        file_id,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO label_example_features(
                        example_id, ocr_text, embedding_json, token_fingerprint, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        example_id,
                        example_text,
                        None,
                        None,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
        conn.commit()
    finally:
        conn.close()

    print("labels.json migration complete.")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS labels(
            label_id TEXT PRIMARY KEY,
            name TEXT,
            is_active INTEGER,
            created_at TEXT,
            extraction_schema_json TEXT,
            naming_template TEXT,
            llm TEXT
        )
        """
    )
    label_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(labels)").fetchall()
    }
    if "llm" not in label_columns:
        conn.execute("ALTER TABLE labels ADD COLUMN llm TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS label_examples(
            example_id TEXT PRIMARY KEY,
            label_id TEXT,
            file_id TEXT,
            filename TEXT,
            created_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS label_example_features(
            example_id TEXT PRIMARY KEY,
            ocr_text TEXT,
            embedding_json TEXT,
            token_fingerprint TEXT,
            updated_at TEXT
        )
        """
    )


def _get_label_id(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute(
        "SELECT label_id FROM labels WHERE name = ? LIMIT 1", (name,)
    ).fetchone()
    return row[0] if row else None


def _label_has_examples(conn: sqlite3.Connection, label_id: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM label_examples WHERE label_id = ?", (label_id,)
    ).fetchone()
    return bool(row and row[0])


if __name__ == "__main__":
    main()
