from __future__ import annotations

import json
import uuid
from pathlib import Path

from typer.testing import CliRunner

from kgmon_mcp import server
from kgmon_runtime.doctor import RuntimeDoctor
from kgmon_runtime.mcp_config import repair_mcp_config
from kgmon_runtime.setup import RuntimeSetup
from kgx_cli import main as kgx_main


def test_setup_local_creates_omc_state_root_and_runtime_config() -> None:
    tmp_path = _workspace("setup")
    result = RuntimeSetup(tmp_path).setup_local()

    assert result.state_root == tmp_path / ".kgmon"
    for relative in (
        "state/sessions",
        "state/missions",
        "state/team",
        "state/interop",
        "state/locks",
        "missions",
        "research",
        "runs",
        "hud",
        "hooks",
        "logs",
    ):
        assert (tmp_path / ".kgmon" / relative).is_dir()

    assert json.loads((tmp_path / ".kgmon/project-memory.json").read_text()) == {
        "schema_version": 1,
        "entries": [],
    }
    assert (tmp_path / ".kgmon/notepad.md").read_text() == "# KGMON Notepad\n"
    assert json.loads((tmp_path / ".kgmon/hud/current.json").read_text()) == {
        "schema_version": 1,
        "active_mode": None,
        "active_competition": None,
        "active_mission": None,
        "security": {"mode": "standard"},
    }

    config = json.loads((tmp_path / ".kgmon/runtime-config.json").read_text())
    assert config == {
        "schema_version": 1,
        "runtime": {
            "name": "kgmon-codex",
            "launcher": "kgx",
            "state_root": ".kgmon",
        },
        "mcp": {
            "server": "kgmon",
            "command": "python",
            "args": ["-m", "kgmon_mcp.stdio"],
        },
        "security": {
            "default_mode": "standard",
            "strict_env_var": "KGMON_SECURITY",
            "auto_submit": "disabled",
        },
    }

    for name in ("events", "hooks", "security", "verification", "mcp"):
        assert (tmp_path / f".kgmon/logs/{name}.jsonl").read_text() == ""


def test_mcp_repair_preserves_existing_servers_and_is_deterministic(
) -> None:
    tmp_path = _workspace("mcp")
    mcp_path = tmp_path / ".mcp.json"
    mcp_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "custom": {"command": "node", "args": ["custom.js"]},
                    "kgmon": {"command": "broken", "args": []},
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    repair_mcp_config(tmp_path)
    first = mcp_path.read_text(encoding="utf-8")
    repair_mcp_config(tmp_path)
    second = mcp_path.read_text(encoding="utf-8")

    assert first == second
    payload = json.loads(first)
    assert payload["mcpServers"]["custom"] == {
        "command": "node",
        "args": ["custom.js"],
    }
    assert payload["mcpServers"]["kgmon"] == {
        "command": "python",
        "args": ["-m", "kgmon_mcp.stdio"],
        "env": {"KGMON_HOME": str(tmp_path.resolve()), "KGMON_SECURITY": "strict"},
        "x-kgmon-managed": True,
    }


def test_runtime_doctor_reports_setup_and_conflicts() -> None:
    tmp_path = _workspace("doctor")
    missing = RuntimeDoctor(tmp_path).check()
    assert missing.ok is False
    assert "missing .kgmon runtime state root" in missing.messages

    RuntimeSetup(tmp_path).setup_local()
    healthy = RuntimeDoctor(tmp_path).check()
    assert healthy.ok is True
    assert healthy.messages == ["kgx runtime skeleton is healthy"]

    conflicts = RuntimeDoctor(tmp_path).check_conflicts()
    assert conflicts.ok is True
    assert conflicts.messages == ["no kgx runtime conflicts detected"]


def test_kgx_setup_and_doctor_commands() -> None:
    tmp_path = _workspace("cli")
    runner = CliRunner()

    setup_result = runner.invoke(
        kgx_main.app,
        ["setup", "--local", "--repo", str(tmp_path)],
    )
    assert setup_result.exit_code == 0
    assert "Created KGMON runtime state root" in setup_result.stdout

    doctor_result = runner.invoke(kgx_main.app, ["doctor", "--repo", str(tmp_path)])
    assert doctor_result.exit_code == 0
    assert "kgx runtime skeleton is healthy" in doctor_result.stdout

    conflicts_result = runner.invoke(
        kgx_main.app,
        ["doctor", "conflicts", "--repo", str(tmp_path)],
    )
    assert conflicts_result.exit_code == 0
    assert "no kgx runtime conflicts detected" in conflicts_result.stdout


def test_mcp_stub_exposes_kgmon_runtime_resources_and_tools() -> None:
    assert "kgmon://state/current" in server.list_resources()
    assert "kgmon://hud/current" in server.list_resources()
    assert "kgmon://logs/events" in server.list_resources()

    assert "kgmon.setup" in server.list_tools()
    assert "kgmon.doctor" in server.list_tools()
    assert "kgmon.hud.get" in server.list_tools()


def _workspace(name: str) -> Path:
    path = Path("test-output") / "m6-runtime" / f"{name}-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    return path
