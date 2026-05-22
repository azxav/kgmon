from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kgmon_agents.handoffs import HandoffLimitError, WorkerHandoff
from kgmon_agents.registry import AgentRegistry
from kgmon_runtime.setup import RuntimeSetup
from kgx_cli import main as kgx_main


def test_agent_registry_defines_m8_lanes_and_worker_contracts() -> None:
    registry = AgentRegistry.default()

    assert registry.get("kgmon:modeler").lane == "build_ml"
    assert registry.get("kgmon:critic").lane == "review"
    assert registry.get("kgmon:tabular-specialist").lane == "domain"
    assert registry.get("kgmon:team-lead").lane == "coordination"

    modelers = registry.allocate("4:modeler")
    assert len(modelers) == 4
    assert {role.id for role in modelers} == {"kgmon:modeler"}
    assert all("kgmon.experiment.run" in role.permitted_tools for role in modelers)
    assert all(role.may_write_final_artifacts is False for role in modelers)


def test_worker_handoffs_are_bounded_descriptors_not_inline_payloads() -> None:
    registry = AgentRegistry.default()
    handoff = WorkerHandoff.create(
        role=registry.get("kgmon:modeler"),
        mission="titanic",
        artifact_type="model_report",
        artifact_path=Path("competitions/titanic/artifacts/reports/modeler.md"),
        summary="baseline trained; see descriptor path",
        metadata={"score": 0.75},
    )

    assert handoff.to_json() == {
        "schema_version": 1,
        "role": "kgmon:modeler",
        "mission": "titanic",
        "artifact": {
            "type": "model_report",
            "path": "competitions/titanic/artifacts/reports/modeler.md",
            "uri": "kgmon://competition/current/artifacts/competitions/titanic/artifacts/reports/modeler.md",
            "metadata": {"score": 0.75},
        },
        "summary": "baseline trained; see descriptor path",
    }

    with pytest.raises(HandoffLimitError):
        WorkerHandoff.create(
            role=registry.get("kgmon:modeler"),
            mission="titanic",
            artifact_type="model_report",
            artifact_path=Path("competitions/titanic/artifacts/reports/large.md"),
            summary="x" * 4097,
        )

    with pytest.raises(HandoffLimitError):
        WorkerHandoff.create(
            role=registry.get("kgmon:modeler"),
            mission="titanic",
            artifact_type="final_package",
            artifact_path=Path("competitions/titanic/artifacts/final/submission.csv"),
            summary="attempted shared final write",
        )


def test_kgx_workflow_modes_create_resumable_state_and_handoffs() -> None:
    tmp_path = _workspace("cli")
    RuntimeSetup(tmp_path).setup_local()
    runner = CliRunner()

    commands = [
        ["deep-interview", "titanic", "--repo", str(tmp_path)],
        ["ralplan", "titanic", "--repo", str(tmp_path)],
        ["team", "4:modeler", "build baseline and ensemble", "--repo", str(tmp_path)],
        ["ralph", "verify and package final solution", "--repo", str(tmp_path)],
        ["ultrawork", "expand model lanes", "--repo", str(tmp_path)],
        ["autopilot", "titanic", "--repo", str(tmp_path)],
    ]

    for command in commands:
        result = runner.invoke(kgx_main.app, command)
        assert result.exit_code == 0, result.stdout

    mission = _read_json(tmp_path / ".kgmon" / "state" / "missions" / "titanic.json")
    assert mission["name"] == "titanic"
    assert mission["competition_slug"] == "titanic"
    assert mission["mode_history"] == [
        "deep-interview",
        "ralplan",
        "team",
        "ralph",
        "ultrawork",
        "autopilot",
    ]
    assert mission["submission_guard"] == {
        "auto_submit": "blocked",
        "requires_confirmation": True,
    }
    assert mission["limits"]["max_iterations"] == 5
    assert mission["limits"]["max_parallel_workers"] == 5

    handoffs = _read_json(
        tmp_path / ".kgmon" / "missions" / "titanic" / "handoffs.json"
    )
    assert [entry["mode"] for entry in handoffs["handoffs"]] == [
        "deep-interview",
        "ralplan",
        "team",
        "ralph",
        "ultrawork",
        "autopilot",
    ]
    assert handoffs["handoffs"][2]["assignment"]["count"] == 4
    assert handoffs["handoffs"][2]["assignment"]["role"] == "kgmon:modeler"
    assert "build baseline and ensemble" not in json.dumps(handoffs)

    active_mode = _read_json(tmp_path / ".kgmon" / "state" / "active-mode.json")
    assert active_mode == {
        "schema_version": 1,
        "mode": "autopilot",
        "mission": "titanic",
    }

    hud = _read_json(tmp_path / ".kgmon" / "hud" / "current.json")
    assert hud["active_mode"] == "autopilot"
    assert hud["active_mission"] == "titanic"
    assert hud["team"]["last_assignment"]["role"] == "kgmon:modeler"
    assert hud["submission"]["auto_submit"] == "blocked"


def _workspace(name: str) -> Path:
    path = Path("test-output") / "m8-modes-agents" / f"{name}-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    return path


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))
