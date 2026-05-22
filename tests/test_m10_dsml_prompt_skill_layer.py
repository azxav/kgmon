from __future__ import annotations

import json
import uuid
from pathlib import Path

from typer.testing import CliRunner

from kgmon_agents.registry import AgentRegistry
from kgmon_runtime.setup import RuntimeSetup
from kgx_cli import main as kgx_main


def test_runtime_setup_installs_dsml_skill_prompt_and_contract_pack() -> None:
    repo = _workspace("setup")

    RuntimeSetup(repo).setup_local()

    skills = _read_json(repo / ".kgmon" / "skills" / "dsml" / "registry.json")
    prompts = _read_json(repo / ".kgmon" / "prompts" / "dsml" / "registry.json")
    contracts = _read_json(
        repo / ".kgmon" / "agent-contracts" / "dsml" / "registry.json"
    )

    assert [skill["id"] for skill in skills["skills"]] == [
        "kgmon-competition-strategist",
        "kgmon-eda-signal-profiler",
        "kgmon-validation-leakage-auditor",
        "kgmon-feature-engineering-factory",
        "kgmon-tabular-gbdt-modeler",
        "kgmon-deep-learning-specialist",
        "kgmon-experiment-ablation-scientist",
        "kgmon-ensemble-stack-optimizer",
        "kgmon-error-analysis-postprocessor",
        "kgmon-final-reproducibility-packager",
        "kgmon-external-data-governor",
        "kgmon-gpu-training-optimizer",
    ]
    assert len(prompts["prompts"]) == 14
    assert {prompt["id"] for prompt in prompts["prompts"]} >= {
        "validation-design",
        "ensemble-search",
    }
    assert {contract["role"] for contract in contracts["contracts"]} >= {
        "kgmon:scout",
        "kgmon:profiler",
        "kgmon:validator",
        "kgmon:feature-engineer",
        "kgmon:modeler",
        "kgmon:ensembler",
        "kgmon:error-analyst",
        "kgmon:external-data-governor",
        "kgmon:verifier",
        "kgmon:packager",
    }
    assert (
        repo / ".kgmon" / "skills" / "dsml" / "kgmon-validation-leakage-auditor.md"
    ).exists()
    assert (repo / ".kgmon" / "prompts" / "dsml" / "validation-design.md").exists()
    assert (
        repo / ".kgmon" / "agent-contracts" / "dsml" / "validator.json"
    ).exists()


def test_kgx_skills_and_prompt_commands_expose_dsml_pack() -> None:
    repo = _workspace("cli")
    RuntimeSetup(repo).setup_local()
    runner = CliRunner()

    list_result = runner.invoke(
        kgx_main.app,
        ["skills", "list", "--domain", "dsml", "--repo", str(repo)],
    )
    inspect_result = runner.invoke(
        kgx_main.app,
        [
            "skills",
            "inspect",
            "kgmon-validation-leakage-auditor",
            "--repo",
            str(repo),
        ],
    )
    prompt_result = runner.invoke(
        kgx_main.app,
        ["prompt", "run", "validation-design", "--repo", str(repo)],
    )

    assert list_result.exit_code == 0
    assert "kgmon-validation-leakage-auditor" in list_result.stdout
    assert "required_before_training" in list_result.stdout
    assert inspect_result.exit_code == 0
    assert "Leakage audit before feature engineering" in inspect_result.stdout
    assert "LEAKAGE_CHECK_PASS" in inspect_result.stdout
    assert prompt_result.exit_code == 0
    assert "Validation before modeling" in prompt_result.stdout
    assert "artifact:" in prompt_result.stdout
    artifact_line = next(
        line
        for line in prompt_result.stdout.splitlines()
        if line.startswith("artifact:")
    )
    artifact_path = repo / artifact_line.removeprefix("artifact:").strip()
    assert artifact_path.exists()


def test_dsml_roles_and_team_route_follow_mandatory_kaggle_ml_order() -> None:
    repo = _workspace("team")
    RuntimeSetup(repo).setup_local()
    runner = CliRunner()

    registry = AgentRegistry.default()
    assert registry.get("kgmon:error-analyst").verification_obligations == (
        "ERROR_ANALYSIS_BACKED_BY_OOF",
    )
    assert registry.get("kgmon:external-data-governor").verification_obligations == (
        "EXTERNAL_DATA_RULE_APPROVED",
    )

    runner.invoke(kgx_main.app, ["deep-interview", "titanic", "--repo", str(repo)])
    result = runner.invoke(
        kgx_main.app,
        ["team", "--domain", "dsml", "--repo", str(repo)],
    )

    assert result.exit_code == 0, result.stdout
    route_path = repo / ".kgmon" / "missions" / "titanic" / "dsml-team" / "route.json"
    route = _read_json(route_path)
    assert [step["stage"] for step in route["pipeline"]] == [
        "strategy",
        "eda",
        "validation",
        "features",
        "modeling",
        "ablation",
        "ensemble",
        "postprocess",
        "package",
        "verify",
    ]
    assert route["core_rules"][0] == "Validation before modeling."
    assert route["core_rules"][1] == "Leakage audit before feature engineering."
    assert route["submission_guard"]["auto_submit"] == "blocked"
    assert all(step["artifact_type"] for step in route["pipeline"])

    handoffs = _read_json(repo / ".kgmon" / "missions" / "titanic" / "handoffs.json")
    latest = handoffs["handoffs"][-1]
    assert latest["mode"] == "team"
    assert latest["handoff"]["type"] == "dsml_team_route"
    assert latest["handoff"]["artifacts"][0]["path"] == (
        "missions/titanic/dsml-team/route.json"
    )


def _workspace(name: str) -> Path:
    path = Path("test-output") / "m10-dsml" / f"{name}-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    return path


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))
