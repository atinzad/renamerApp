from __future__ import annotations

from typing import Iterable

import json

import requests

from app.domain.models import FileRef
from app.ports.drive_port import DrivePort


class GoogleDriveAdapter(DrivePort):
    _BASE_URL = "https://www.googleapis.com/drive/v3"
    _UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3"

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
                "supportsAllDrives": True,
                "includeItemsFromAllDrives": True,
                "corpora": "allDrives",
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
                files.append(
                    FileRef(
                        file_id=item.get("id", ""),
                        name=item.get("name", ""),
                        mime_type=item.get("mimeType", ""),
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

    def upload_text_file(self, folder_id: str, filename: str, content: str) -> str:
        metadata = {"name": filename, "parents": [folder_id], "mimeType": "text/plain"}
        boundary = "renamerapp-upload-boundary"
        metadata_part = json.dumps(metadata)
        media_part = content
        body = (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{metadata_part}\r\n"
            f"--{boundary}\r\n"
            "Content-Type: text/plain; charset=UTF-8\r\n\r\n"
            f"{media_part}\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        response = requests.post(
            f"{self._UPLOAD_URL}/files",
            headers={
                **self._auth_header(),
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            params={"uploadType": "multipart", "supportsAllDrives": True},
            data=body,
            timeout=20,
        )
        self._raise_for_status(response, context="upload text file")
        payload = response.json()
        file_id = payload.get("id")
        if not file_id:
            raise RuntimeError("Drive API response missing file id after upload.")
        return file_id

    def _auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    @staticmethod
    def _raise_for_status(response: requests.Response, context: str) -> None:
        if response.status_code in (401, 403):
            raise RuntimeError(f"Auth failed while attempting to {context}.")
        if response.status_code == 404:
            raise RuntimeError(f"Resource not found or no access while attempting to {context}.")
        if response.status_code >= 400:
            detail = response.text.strip()
            if detail:
                raise RuntimeError(
                    f"Drive API error {response.status_code} while attempting to {context}: {detail}"
                )
            raise RuntimeError(f"Drive API error {response.status_code} while attempting to {context}.")
