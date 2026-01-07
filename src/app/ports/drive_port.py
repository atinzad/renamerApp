from __future__ import annotations

from typing import Protocol

from app.domain.models import FileRef


class DrivePort(Protocol):
    def list_folder_files(self, folder_id: str) -> list[FileRef]:
        """Return files for a folder in stable order."""

    def rename_file(self, file_id: str, new_name: str) -> None:
        """Rename a file by id."""

    def upload_text_file(self, folder_id: str, filename: str, content: str) -> str:
        """Upload a text file and return the created file id."""
