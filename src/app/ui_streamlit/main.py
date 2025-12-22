from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_SRC_ROOT = Path(__file__).resolve().parents[2]
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from app.container import build_services


def _init_state() -> None:
    st.session_state.setdefault("services", None)
    st.session_state.setdefault("job_id", None)
    st.session_state.setdefault("files", [])
    st.session_state.setdefault("preview_ops", [])


def _get_services(access_token: str, sqlite_path: str):
    if st.session_state["services"] is None:
        st.session_state["services"] = build_services(access_token, sqlite_path)
    return st.session_state["services"]


def main() -> None:
    st.title("Google Drive Image Renamer")
    _init_state()

    access_token = st.text_input("Access Token", type="password")
    folder_id = st.text_input("Folder ID")
    sqlite_path = st.text_input("SQLite Path", value="./app.db")

    cols = st.columns(4)
    create_clicked = cols[0].button("Create Job")
    preview_clicked = cols[1].button("Preview")
    apply_clicked = cols[2].button("Apply Rename")
    undo_clicked = cols[3].button("Undo Last")

    if create_clicked:
        try:
            services = _get_services(access_token, sqlite_path)
            job = services["jobs_service"].create_job(folder_id)
            files = services["jobs_service"].list_files(job.job_id)
            st.session_state["job_id"] = job.job_id
            st.session_state["files"] = files
            st.session_state["preview_ops"] = []
            st.success(f"Job created: {job.job_id}")
        except Exception as exc:
            st.error(f"Create job failed: {exc}")

    job_id = st.session_state.get("job_id")
    if job_id:
        st.subheader("Job")
        st.write(f"Job ID: {job_id}")

    files = st.session_state.get("files", [])
    if files:
        st.subheader("Files")
        for file_ref in files:
            st.write(f"{file_ref.name} ({file_ref.file_id})")

        st.subheader("Manual Rename Editor")
        edits = {}
        for file_ref in files:
            key = f"edit_{file_ref.file_id}"
            new_name = st.text_input(
                f"New name for {file_ref.name}",
                value=st.session_state.get(key, ""),
                key=key,
            )
            if new_name.strip():
                edits[file_ref.file_id] = new_name
    else:
        edits = {}

    if preview_clicked:
        try:
            services = _get_services(access_token, sqlite_path)
            if job_id is None:
                raise RuntimeError("No job has been created yet.")
            ops = services["rename_service"].preview_manual_rename(job_id, edits)
            st.session_state["preview_ops"] = ops
            if ops:
                st.subheader("Preview Plan")
                st.table(
                    [
                        {
                            "file_id": op.file_id,
                            "old_name": op.old_name,
                            "new_name": op.new_name,
                        }
                        for op in ops
                    ]
                )
            else:
                st.info("No rename operations to preview.")
        except Exception as exc:
            st.error(f"Preview failed: {exc}")

    if apply_clicked:
        try:
            services = _get_services(access_token, sqlite_path)
            if job_id is None:
                raise RuntimeError("No job has been created yet.")
            ops = st.session_state.get("preview_ops") or services["rename_service"].preview_manual_rename(
                job_id, edits
            )
            services["rename_service"].apply_rename(job_id, ops)
            st.success("Rename applied.")
        except Exception as exc:
            st.error(f"Apply rename failed: {exc}")

    if undo_clicked:
        try:
            services = _get_services(access_token, sqlite_path)
            if job_id is None:
                raise RuntimeError("No job has been created yet.")
            services["rename_service"].undo_last(job_id)
            st.success("Undo completed.")
        except Exception as exc:
            st.error(f"Undo failed: {exc}")


if __name__ == "__main__":
    main()
