from __future__ import annotations

import os
from pathlib import Path


class WorkspaceResolutionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_workspace(
    *,
    cwd: Path | str | None = None,
    workspace_root: Path | str | None = None,
) -> Path:
    env_home = os.environ.get("KGMON_HOME")
    if env_home:
        return _valid_workspace(Path(env_home), "KGMON_HOME")

    current = Path.cwd() if cwd is None else Path(cwd)
    if (current / ".kgmon").exists():
        return current.resolve()

    parent_with_state = _nearest_parent(current, ".kgmon")
    if parent_with_state is not None:
        return parent_with_state.resolve()

    parent_with_repo = _nearest_repo_parent(current)
    if parent_with_repo is not None:
        return parent_with_repo.resolve()

    if workspace_root is not None:
        return _valid_workspace(Path(workspace_root), "workspace_root")

    raise WorkspaceResolutionError(
        "KGMON_HOME_NOT_FOUND",
        "Set KGMON_HOME, launch inside a KGMON workspace, or pass workspace_root.",
    )


def _valid_workspace(path: Path, source: str) -> Path:
    resolved = path.expanduser().resolve()
    has_repo_markers = (resolved / "pyproject.toml").exists() and (
        resolved / "kgmon_core"
    ).exists()
    if (
        (resolved / ".kgmon").exists()
        or has_repo_markers
    ):
        return resolved
    raise WorkspaceResolutionError(
        "KGMON_HOME_NOT_FOUND",
        f"{source} does not point to a KGMON workspace: {resolved}",
    )


def _nearest_parent(start: Path, marker: str) -> Path | None:
    for path in (start, *start.parents):
        if (path / marker).exists():
            return path
    return None


def _nearest_repo_parent(start: Path) -> Path | None:
    for path in (start, *start.parents):
        if (path / "pyproject.toml").exists() and (path / "kgmon_core").exists():
            return path
    return None
