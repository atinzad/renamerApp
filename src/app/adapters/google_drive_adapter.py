from __future__ import annotations

from typing import Iterable

import requests

from app.domain.models import FileRef
from app.ports.drive_port import DrivePort


class GoogleDriveAdapter(DrivePort):
    _BASE_URL = "https://www.googleapis.com/drive/v3"

    def __init__(self, access_token: str) -> None:
        self._access_token = access_token

    def list_folder_files(self, folder_id: str) -> list[FileRef]:
        files: list[FileRef] = []
        page_token: str | None = None
        query = f"'{folder_id}' in parents and trashed=false"
        while True:
            params = {
                "q": query,
                "fields": "nextPageToken, files(id, name, mimeType)",
                "pageSize": 1000,
            }
            if page_token:
                params["pageToken"] = page_token
            response = requests.get(
                f"{self._BASE_URL}/files",
                headers=self._auth_header(),
                params=params,
                timeout=20,
            )
            self._raise_for_status(response, context="list folder files")
            payload = response.json()
            for item in payload.get("files", []):
                mime_type = item.get("mimeType", "")
                if not mime_type.startswith("image/"):
                    continue
                files.append(
                    FileRef(
                        file_id=item.get("id", ""),
                        name=item.get("name", ""),
                        mime_type=mime_type,
                    )
                )
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        return files

    def rename_file(self, file_id: str, new_name: str) -> None:
        response = requests.patch(
            f"{self._BASE_URL}/files/{file_id}",
            headers={**self._auth_header(), "Content-Type": "application/json"},
            json={"name": new_name},
            timeout=20,
        )
        self._raise_for_status(response, context="rename file")

    def _auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    @staticmethod
    def _raise_for_status(response: requests.Response, context: str) -> None:
        if response.status_code in (401, 403):
            raise RuntimeError(f"Auth failed while attempting to {context}.")
        if response.status_code == 404:
            raise RuntimeError(f"Resource not found or no access while attempting to {context}.")
        if response.status_code >= 400:
            raise RuntimeError(
                f"Drive API error {response.status_code} while attempting to {context}."
            )
