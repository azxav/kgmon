from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from kgmon_mcp.context import WorkspaceResolutionError, resolve_workspace
from kgmon_mcp.schemas import failure, success
from kgmon_mcp.server import list_public_tools, public_tool_schemas
from kgmon_runtime.setup import RuntimeSetup


def test_result_envelopes_are_simple_json_compatible_shapes() -> None:
    ok = success({"status": "ok"}, warnings=["note"], next_actions=["kgmon_hud_get"])
    failed = failure("KGMON_HOME_NOT_FOUND", "workspace missing")

    assert ok == {
        "ok": True,
        "data": {"status": "ok"},
        "warnings": ["note"],
        "artifacts": [],
        "next_actions": ["kgmon_hud_get"],
    }
    assert failed == {
        "ok": False,
        "error": {
            "code": "KGMON_HOME_NOT_FOUND",
            "message": "workspace missing",
            "recoverable": True,
        },
        "warnings": [],
        "artifacts": [],
        "next_actions": [],
    }
    json.dumps(ok)
    json.dumps(failed)


def test_workspace_resolution_order_uses_env_cwd_parent_repo_then_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_repo = _workspace("env")
    cwd_repo = _workspace("cwd")
    parent_repo = _workspace("parent")
    explicit_repo = _workspace("explicit")
    RuntimeSetup(env_repo).setup_local()
    RuntimeSetup(cwd_repo).setup_local()
    RuntimeSetup(parent_repo).setup_local()
    RuntimeSetup(explicit_repo).setup_local()
    nested = parent_repo / "a" / "b"
    nested.mkdir(parents=True)

    monkeypatch.setenv("KGMON_HOME", str(env_repo))
    assert (
        resolve_workspace(cwd=cwd_repo, workspace_root=explicit_repo)
        == env_repo.resolve()
    )
    monkeypatch.delenv("KGMON_HOME")
    assert (
        resolve_workspace(cwd=cwd_repo, workspace_root=explicit_repo)
        == cwd_repo.resolve()
    )
    assert (
        resolve_workspace(cwd=nested, workspace_root=explicit_repo)
        == parent_repo.resolve()
    )
    non_workspace = Path(Path.cwd().anchor) / "__kgmon_missing_workspace__"
    assert (
        resolve_workspace(cwd=non_workspace, workspace_root=explicit_repo)
        == explicit_repo.resolve()
    )

    with pytest.raises(WorkspaceResolutionError) as excinfo:
        resolve_workspace(cwd=non_workspace)
    assert excinfo.value.code == "KGMON_HOME_NOT_FOUND"


def test_public_tool_schemas_use_underscore_names_and_simple_parameters() -> None:
    tools = list_public_tools()
    schemas = public_tool_schemas()

    assert "kgmon_doctor" in tools
    assert "kgmon.validation.plan" not in tools
    assert tools == sorted(tools)
    assert set(schemas) == set(tools)
    for name, schema in schemas.items():
        assert "." not in name
        assert schema["type"] == "object"
        properties = schema["properties"]
        assert isinstance(properties, dict)
        assert all("anyOf" not in json.dumps(prop) for prop in properties.values())


def _workspace(name: str) -> Path:
    path = Path("test-output") / "m11-schema" / f"{name}-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    return path
