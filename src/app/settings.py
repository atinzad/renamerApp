from __future__ import annotations

import os

GOOGLE_DRIVE_ACCESS_TOKEN = os.getenv("GOOGLE_DRIVE_ACCESS_TOKEN", "")
SQLITE_PATH = os.getenv("SQLITE_PATH", "./app.db")
