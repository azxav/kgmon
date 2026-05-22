from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kgmon_core.ensembles import EnsembleEngine
from kgmon_core.experiments import BaselineExperimentPlanner, ExperimentDagRunner
from kgmon_core.packaging import SubmissionPackager
from kgmon_mcp.server import run_tool
from kgmon_modes.workflows import WorkflowModeRunner
from kgmon_runtime.security import SecurityPolicy, SecurityViolation
from kgmon_runtime.setup import RuntimeSetup
from kgmon_runtime.verification import REQUIRED_GATES, VerificationEngine
from kgx_cli import main as kgx_main


def test_verification_engine_writes_fresh_gate_evidence_and_hud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _workspace("engine")
    workspace = _complete_competition(repo)
    _activate(repo, workspace)
    monkeypatch.setenv("KAGGLE_API_TOKEN", "kg-secret-token")
    monkeypatch.setenv("KGMON_SECURITY", "strict")

    report = VerificationEngine(repo).verify_all()

    assert report.ok is True
    assert [evidence.gate for evidence in report.evidence] == list(REQUIRED_GATES)
    assert all(evidence.status == "pass" for evidence in report.evidence)

    evidence_path = repo / ".kgmon" / "missions" / "titanic" / "verification.json"
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["critical_failures"] == 0
    assert payload["fresh"] is True
    assert payload["evidence"][0]["checked_at"].endswith("Z")
    assert "kg-secret-token" not in evidence_path.read_text(encoding="utf-8")

    hud = json.loads((repo / ".kgmon" / "hud" / "current.json").read_text())
    assert hud["active_competition"] == "titanic"
    assert hud["verification"]["passed"] == len(REQUIRED_GATES)
    assert hud["verification"]["critical_failures"] == 0
    assert hud["security"]["mode"] == "strict"

    verification_logs = _read_jsonl(repo / ".kgmon" / "logs" / "verification.jsonl")
    assert verification_logs[-1]["ok"] is True


def test_kgx_m9_commands_support_strict_doctor_hud_replay_and_verify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _workspace("cli")
    workspace = _complete_competition(repo)
    _activate(repo, workspace)
    monkeypatch.setenv("KAGGLE_API_TOKEN", "kg-secret-token")
    monkeypatch.setenv("KGMON_SECURITY", "strict")
    runner = CliRunner()

    doctor = runner.invoke(kgx_main.app, ["doctor", "--repo", str(repo)])
    verify = runner.invoke(kgx_main.app, ["verify", "all", "--repo", str(repo)])
    hud = runner.invoke(kgx_main.app, ["hud", "--repo", str(repo)])
    status = runner.invoke(kgx_main.app, ["status", "--repo", str(repo)])
    replay = runner.invoke(kgx_main.app, ["replay", "latest", "--repo", str(repo)])

    assert doctor.exit_code == 0
    assert "strict security mode is healthy" in doctor.stdout
    assert verify.exit_code == 0
    expected_verify = (
        f"verification: {len(REQUIRED_GATES)}/{len(REQUIRED_GATES)} gates passed"
    )
    assert expected_verify in verify.stdout
    assert "critical_failures: 0" in verify.stdout
    assert hud.exit_code == 0
    assert "security: strict" in hud.stdout
    assert "verification:" in hud.stdout
    assert status.exit_code == 0
    assert "gates:" in status.stdout
    assert replay.exit_code == 0
    assert "VERIFY_COMPLETED" in replay.stdout
    assert "kg-secret-token" not in replay.stdout
    security_logs = _read_jsonl(repo / ".kgmon" / "logs" / "security.jsonl")
    assert any(entry["event"] == "strict_doctor_checked" for entry in security_logs)


def test_mcp_verify_tool_returns_gate_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _workspace("mcp")
    workspace = _complete_competition(repo)
    _activate(repo, workspace)
    monkeypatch.setenv("KAGGLE_API_TOKEN", "kg-secret-token")
    monkeypatch.setenv("KGMON_SECURITY", "strict")

    result = run_tool("kgmon.verify.all", {"workspace": str(repo)})
    hud = run_tool("kgmon.hud.get", {"workspace": str(repo)})

    assert result["status"] == "completed"
    assert result["passed"] == len(REQUIRED_GATES)
    assert result["critical_failures"] == 0
    assert result["evidence_path"].endswith("verification.json")
    assert hud["verification"]["passed"] == len(REQUIRED_GATES)
    assert "kg-secret-token" not in json.dumps(result)


def test_strict_security_policy_blocks_paths_external_data_and_unconfirmed_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _workspace("security")
    workspace = _complete_competition(repo, external_data=True)
    _activate(repo, workspace)
    monkeypatch.setenv("KAGGLE_API_TOKEN", "kg-secret-token")
    monkeypatch.setenv("KGMON_SECURITY", "strict")
    runner = CliRunner()

    policy = SecurityPolicy.for_repo(repo)
    policy.require_path_allowed(repo / "competitions" / "titanic" / "artifacts")
    with pytest.raises(SecurityViolation):
        policy.require_path_allowed(repo.parent / "outside.txt")

    verify = runner.invoke(kgx_main.app, ["verify", "all", "--repo", str(repo)])
    submit = runner.invoke(
        kgx_main.app,
        [
            "submit",
            "--final",
            "--require-confirmation",
            "--workspace",
            str(workspace),
            "--repo",
            str(repo),
        ],
    )

    assert verify.exit_code == 1
    assert "NO_UNAPPROVED_EXTERNAL_DATA: fail" in verify.stdout
    assert submit.exit_code == 1
    assert "explicit confirmation is required" in submit.stdout

    security_logs = _read_jsonl(repo / ".kgmon" / "logs" / "security.jsonl")
    assert any(entry["event"] == "path_denied" for entry in security_logs)
    assert any(entry["event"] == "submission_blocked" for entry in security_logs)
    assert "kg-secret-token" not in json.dumps(security_logs)


def _complete_competition(repo: Path, *, external_data: bool = False) -> Path:
    workspace = repo / "competitions" / "titanic"
    (workspace / "configs").mkdir(parents=True)
    (workspace / "data" / "raw").mkdir(parents=True)
    (workspace / "data" / "processed").mkdir(parents=True)
    (workspace / "artifacts" / "reports").mkdir(parents=True)
    (workspace / "kaggle" / "pages").mkdir(parents=True)

    (workspace / "configs" / "competition.yaml").write_text(
        f"""competition:
  slug: titanic
  source: kaggle
  task_family: tabular_binary_classification
  target_column: Survived
  id_column: PassengerId
  metric:
    name: accuracy
    direction: maximize
  submission:
    id_column: PassengerId
    prediction_columns: [Survived]

rules:
  external_data: {str(external_data).lower()}
  auto_submit_allowed: false
  human_review_required: false

data:
  train_path: data/raw/train.csv
  test_path: data/raw/test.csv
  sample_submission_path: data/raw/gender_submission.csv

validation:
  strategy: StratifiedKFold
  n_folds: 3
  seed: 42
""",
        encoding="utf-8",
    )
    (workspace / "configs" / "validation.yaml").write_text(
        """strategy: StratifiedKFold
n_folds: 3
seed: 42
folds_path: data/processed/folds.csv
status: ready
leakage_check: pass
warnings:
  []
""",
        encoding="utf-8",
    )
    (workspace / "artifacts" / "reports" / "profile.json").write_text(
        json.dumps({"schema_version": 1, "rows": {"train": 6, "test": 2}}),
        encoding="utf-8",
    )
    (workspace / "kaggle" / "pages" / "rules.md").write_text(
        "Rules audited by KGMON.",
        encoding="utf-8",
    )
    (workspace / "data" / "raw" / "train.csv").write_text(
        "\n".join(
            [
                "PassengerId,Survived,Name,Fare",
                "1,0,A,7.25",
                "2,1,B,71.28",
                "3,1,C,7.92",
                "4,0,D,8.05",
                "5,0,E,8.45",
                "6,1,F,51.86",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (workspace / "data" / "raw" / "test.csv").write_text(
        "PassengerId,Name,Fare\n7,G,9.00\n8,H,500.00\n",
        encoding="utf-8",
    )
    (workspace / "data" / "raw" / "gender_submission.csv").write_text(
        "PassengerId,Survived\n7,0\n8,1\n",
        encoding="utf-8",
    )
    (workspace / "data" / "processed" / "folds.csv").write_text(
        "\n".join(
            [
                "row_index,id,target,fold",
                "0,1,0,0",
                "1,2,1,0",
                "2,3,1,1",
                "3,4,0,1",
                "4,5,0,2",
                "5,6,1,2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    BaselineExperimentPlanner(workspace).plan(mode="baseline")
    ExperimentDagRunner(workspace).run()
    EnsembleEngine(workspace).search()
    SubmissionPackager(workspace).package_final()
    return workspace


def _activate(repo: Path, workspace: Path) -> None:
    RuntimeSetup(repo).setup_local()
    WorkflowModeRunner(repo).autopilot("titanic")
    mission_path = repo / ".kgmon" / "state" / "missions" / "titanic.json"
    mission = json.loads(mission_path.read_text(encoding="utf-8"))
    mission["workspace"] = workspace.relative_to(repo).as_posix()
    mission_path.write_text(json.dumps(mission, indent=2) + "\n", encoding="utf-8")


def _workspace(name: str) -> Path:
    path = Path("test-output") / "m9-runtime" / f"{name}-{uuid.uuid4().hex}"
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    return path


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
