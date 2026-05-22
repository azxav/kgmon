from __future__ import annotations

import json
import uuid
from pathlib import Path

from typer.testing import CliRunner

from kgmon_mcp.server import (
    list_mcp_prompts,
    list_mcp_resources,
    read_mcp_resource,
    run_public_tool,
)
from kgmon_runtime.setup import RuntimeSetup
from kgx_cli import main as kgx_main


def test_public_mcp_tools_resources_and_prompts_use_m11_contracts(
    monkeypatch,
) -> None:
    repo = _workspace("contracts")
    RuntimeSetup(repo).setup_local()
    monkeypatch.setenv("KGMON_HOME", str(repo))

    doctor = run_public_tool("kgmon_doctor", {"workspace_root": str(repo)})
    hud = run_public_tool("kgmon_hud_get", {"workspace_root": str(repo)})
    skills = run_public_tool("kgmon_skills_list", {"workspace_root": str(repo)})
    prompts = run_public_tool("kgmon_prompts_list", {"workspace_root": str(repo)})
    prompt_run = run_public_tool(
        "kgmon_prompt_run",
        {"workspace_root": str(repo), "prompt_id": "kgmon_validation_design"},
    )

    assert doctor["ok"] is True
    assert doctor["data"]["status"] == "ok"
    assert hud["ok"] is True
    assert skills["ok"] is True
    assert "kgmon-validation-leakage-auditor" in json.dumps(skills["data"])
    assert prompts["ok"] is True
    assert "kgmon_validation_design" in json.dumps(prompts["data"])
    assert prompt_run["ok"] is True
    assert prompt_run["artifacts"][0]["path"].endswith(
        ".kgmon/prompts/dsml/runs/validation-design.md"
    )

    resources = list_mcp_resources()
    prompt_defs = list_mcp_prompts()
    assert "kgmon://competition/current/runs" in [item["uri"] for item in resources]
    assert "kgmon_modeling_plan" in [item["name"] for item in prompt_defs]
    state = read_mcp_resource("kgmon://state/current", workspace_root=str(repo))
    assert state["ok"] is True
    assert state["data"]["schema_version"] == 1


def test_kgx_mcp_install_and_doctor_generate_client_templates() -> None:
    repo = _workspace("cli")
    runner = CliRunner()

    install = runner.invoke(
        kgx_main.app,
        ["mcp", "install", "--client", "codex", "--repo", str(repo)],
    )
    doctor = runner.invoke(
        kgx_main.app,
        ["mcp", "doctor", "--client", "codex", "--repo", str(repo)],
    )

    assert install.exit_code == 0, install.stdout
    assert "kgmon_mcp.stdio" in install.stdout
    payload = json.loads((repo / ".mcp.json").read_text(encoding="utf-8"))
    assert payload["mcpServers"]["kgmon"]["args"] == ["-m", "kgmon_mcp.stdio"]
    assert payload["mcpServers"]["kgmon"]["env"]["KGMON_HOME"] == str(repo.resolve())
    assert doctor.exit_code == 0, doctor.stdout
    assert "codex MCP config is healthy" in doctor.stdout


def _workspace(name: str) -> Path:
    path = Path("test-output") / "m11-contracts" / f"{name}-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    return path
