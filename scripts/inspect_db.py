from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_REPO_ROOT / ".env", override=False)


def main() -> None:
    db_path = os.getenv("SQLITE_PATH", "app.db")
    conn = sqlite3.connect(db_path)
    try:
        print("DB:", db_path)
        print("Tables:")
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ):
            print("-", row[0])

        print("\nLabels:")
        for row in conn.execute(
            "SELECT label_id, name, is_active FROM labels ORDER BY created_at DESC LIMIT 10"
        ):
            print(row)

        print("\nLabel examples:")
        for row in conn.execute(
            "SELECT example_id, label_id, file_id FROM label_examples LIMIT 10"
        ):
            print(row)

        print("\nOCR results:")
        row = conn.execute("SELECT COUNT(*) FROM ocr_results").fetchone()
        print("count:", row[0] if row else 0)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
