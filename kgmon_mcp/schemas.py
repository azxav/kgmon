from __future__ import annotations

from pathlib import Path
from typing import Any


def success(
    data: dict[str, Any] | None = None,
    *,
    warnings: list[str] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    next_actions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "data": data or {},
        "warnings": warnings or [],
        "artifacts": artifacts or [],
        "next_actions": next_actions or [],
    }


def failure(
    code: str,
    message: str,
    *,
    recoverable: bool = True,
    warnings: list[str] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    next_actions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "recoverable": recoverable,
        },
        "warnings": warnings or [],
        "artifacts": artifacts or [],
        "next_actions": next_actions or [],
    }


def artifact_descriptor(
    path: Path,
    *,
    kind: str,
    workspace: Path | None = None,
    mime_type: str = "application/octet-stream",
) -> dict[str, Any]:
    descriptor_path = path
    if workspace is not None:
        try:
            descriptor_path = path.relative_to(workspace)
        except ValueError:
            descriptor_path = path
    return {
        "kind": kind,
        "path": descriptor_path.as_posix(),
        "mime_type": mime_type,
    }
