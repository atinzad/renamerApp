from __future__ import annotations

from typing import Iterable

from .models import FileRef, RenameOp

INVALID_FILENAME_CHARS = set('/\\:*?"<>|')


def sanitize_filename(name: str) -> str:
    """
    Remove invalid filename characters and control chars, normalize whitespace,
    and ensure a non-empty result.

    Examples:
        >>> sanitize_filename("  a/b  ")
        'ab'
        >>> sanitize_filename("   ")
        'UNNAMED'
        >>> sanitize_filename("report\\n.txt")
        'report.txt'
    """
    filtered = []
    for ch in name:
        if ch in INVALID_FILENAME_CHARS:
            continue
        codepoint = ord(ch)
        if codepoint < 32 or codepoint == 127:
            continue
        filtered.append(ch)

    collapsed = " ".join("".join(filtered).split())
    normalized = collapsed.strip()
    return normalized if normalized else "UNNAMED"


def build_manual_plan(files: list[FileRef], edits: dict[str, str]) -> list[RenameOp]:
    """
    Create rename operations for files with a non-empty desired name.

    Example:
        files = [FileRef("1", "old.png", "image/png")]
        edits = {"1": "new.png"}
        build_manual_plan(files, edits)
        # [RenameOp(file_id='1', old_name='old.png', new_name='new.png')]
    """
    ops: list[RenameOp] = []
    for file_ref in files:
        desired = edits.get(file_ref.file_id)
        if desired is None or desired.strip() == "":
            continue
        ops.append(RenameOp(file_id=file_ref.file_id, old_name=file_ref.name, new_name=desired))
    return ops


def resolve_collisions(ops: list[RenameOp], existing_names: set[str]) -> list[RenameOp]:
    """
    Apply a deterministic collision policy to proposed rename operations.

    Example:
        ops = [RenameOp("1", "a.png", "photo.png"), RenameOp("2", "b.png", "photo.png")]
        resolve_collisions(ops, {"photo.png"})
        # ['photo_01.png', 'photo_02.png']
    """
    used_names = set(existing_names)
    resolved: list[RenameOp] = []
    for op in ops:
        candidate = op.new_name
        if candidate in used_names:
            candidate = _next_available_name(candidate, used_names)
        used_names.add(candidate)
        resolved.append(RenameOp(file_id=op.file_id, old_name=op.old_name, new_name=candidate))
    return resolved


def _next_available_name(name: str, used_names: set[str]) -> str:
    base, ext = _split_extension(name)
    counter = 1
    while True:
        candidate = f"{base}_{counter:02d}{ext}"
        if candidate not in used_names:
            return candidate
        counter += 1


def _split_extension(name: str) -> tuple[str, str]:
    """
    Split a filename into (base, extension), keeping the dot in the extension.
    """
    base, dot, ext = name.rpartition(".")
    if dot == "":
        return name, ""
    if base == "":
        return "", f".{ext}"
    return base, f".{ext}"
