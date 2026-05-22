from __future__ import annotations

import csv
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kgmon_cli.main import app
from kgmon_core.ensembles import EnsembleEngine
from kgmon_core.experiments import BaselineExperimentPlanner, ExperimentDagRunner
from kgmon_core.kaggle_bridge import KaggleNotebookBridge, SubmissionBridge
from kgmon_core.packaging import SubmissionPackager
from kgmon_mcp.server import list_resources, list_tools, read_resource, run_tool


def _write_workspace(root: Path) -> Path:
    workspace = root / "competitions" / "titanic"
    shutil.rmtree(root, ignore_errors=True)
    (workspace / "configs").mkdir(parents=True)
    (workspace / "data" / "raw").mkdir(parents=True)
    (workspace / "data" / "processed").mkdir(parents=True)
    (workspace / "artifacts" / "reports").mkdir(parents=True)
    (workspace / "artifacts" / "registry.sqlite").parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    (workspace / "configs" / "competition.yaml").write_text(
        """competition:
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
  auto_submit_allowed: false
  human_review_required: true

data:
  train_path: data/raw/train.csv
  test_path: data/raw/test.csv
  sample_submission_path: data/raw/gender_submission.csv

validation:
  strategy: StratifiedKFold
  group_column: null
  time_column: null
  n_folds: 3
  seed: 42

resources:
  backend: local
  max_parallel_runs: 2
""",
        encoding="utf-8",
    )
    (workspace / "configs" / "validation.yaml").write_text(
        """strategy: StratifiedKFold
n_folds: 3
seed: 42
folds_path: data/processed/folds.csv
status: ready
warnings:
  []
""",
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
    return workspace


def test_dag_runner_executes_baseline_and_registers_lineage() -> None:
    workspace = _write_workspace(Path("test-output") / "m5-dag")
    BaselineExperimentPlanner(workspace).plan(mode="baseline")
    dag_path = workspace / "configs" / "experiments" / "baseline_dag.yaml"
    dag_path.parent.mkdir(parents=True)
    dag_path.write_text(
        """experiments:
  - id: baseline-sklearn-dummy
    spec_path: configs/model_params/baseline_sklearn_dummy.yaml
    depends_on: []
    retry: 1
""",
        encoding="utf-8",
    )

    result = ExperimentDagRunner(workspace).run(dag_path)

    assert result.completed == ["baseline-sklearn-dummy"]
    assert result.failed == []
    with sqlite3.connect(workspace / "artifacts" / "registry.sqlite") as connection:
        run_rows = connection.execute(
            "select id, status, metric_name from runs"
        ).fetchall()
        artifact_rows = connection.execute(
            "select run_id, type, path from artifacts order by type"
        ).fetchall()
    assert run_rows == [("baseline-sklearn-dummy", "completed", "accuracy")]
    assert artifact_rows == [
        (
            "baseline-sklearn-dummy",
            "model",
            "artifacts/models/baseline-sklearn-dummy.json",
        ),
        (
            "baseline-sklearn-dummy",
            "oof_predictions",
            "artifacts/oof/baseline-sklearn-dummy.csv",
        ),
        (
            "baseline-sklearn-dummy",
            "report",
            "runs/baseline-sklearn-dummy/run_report.json",
        ),
        (
            "baseline-sklearn-dummy",
            "test_predictions",
            "artifacts/test_preds/baseline-sklearn-dummy.csv",
        ),
    ]


def test_m5_cli_runs_dag_and_lists_registered_artifacts() -> None:
    workspace = _write_workspace(Path("test-output") / "m5-cli-dag")
    BaselineExperimentPlanner(workspace).plan(mode="baseline")
    dag_path = workspace / "configs" / "experiments" / "baseline_dag.yaml"
    dag_path.parent.mkdir(parents=True)
    dag_path.write_text(
        """experiments:
  - id: baseline-sklearn-dummy
    spec_path: configs/model_params/baseline_sklearn_dummy.yaml
    depends_on: []
""",
        encoding="utf-8",
    )
    runner = CliRunner()

    run_result = runner.invoke(
        app,
        ["experiment", "run", "--dag", str(dag_path), "--workspace", str(workspace)],
    )
    list_result = runner.invoke(
        app,
        ["artifacts", "list", "--workspace", str(workspace)],
    )

    assert run_result.exit_code == 0
    assert "DAG completed: baseline-sklearn-dummy" in run_result.stdout
    assert list_result.exit_code == 0
    assert "baseline-sklearn-dummy" in list_result.stdout
    assert "oof_predictions" in list_result.stdout


def test_ensemble_search_and_final_packager_create_m5_outputs() -> None:
    workspace = _write_workspace(Path("test-output") / "m5-ensemble")
    BaselineExperimentPlanner(workspace).plan(mode="baseline")
    ExperimentDagRunner(workspace).run()

    ensemble = EnsembleEngine(workspace).search()
    package = SubmissionPackager(workspace).package_final()

    assert ensemble.config_path == workspace / "artifacts" / "ensembles" / (
        "ensemble_v001.yaml"
    )
    assert ensemble.submission_path == workspace / "artifacts" / "submissions" / (
        "submission_ensemble_v001.csv"
    )
    with ensemble.submission_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == ["PassengerId", "Survived"]
    assert [row["PassengerId"] for row in rows] == ["7", "8"]

    expected_final = {
        "submission.csv",
        "inference.py",
        "solution.ipynb",
        "requirements.txt",
        "environment.yml",
        "manifest.yaml",
        "provenance.json",
        "report.md",
    }
    assert expected_final.issubset(
        {path.name for path in package.final_dir.iterdir() if path.is_file()}
    )
    provenance = json.loads((package.final_dir / "provenance.json").read_text())
    assert provenance["ensemble"]["id"] == "ensemble_v001"


class FakeKaggleAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def push_notebook(self, notebook_path: Path, metadata: dict[str, object]) -> str:
        self.calls.append(("push", notebook_path.name))
        return "azxav/titanic-final"

    def run_notebook(self, notebook_ref: str) -> str:
        self.calls.append(("run", notebook_ref))
        return "job-123"

    def download_notebook_output(self, notebook_ref: str, output_dir: Path) -> Path:
        self.calls.append(("fetch_output", notebook_ref))
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "submission.csv"
        output_path.write_text("PassengerId,Survived\n7,0\n", encoding="utf-8")
        return output_path

    def submit_predictions(self, slug: str, submission_path: Path, message: str) -> str:
        self.calls.append(("submit", slug))
        return "submitted"


def test_notebook_and_submission_bridge_archive_outputs_and_guard_submit() -> None:
    workspace = _write_workspace(Path("test-output") / "m5-bridge")
    BaselineExperimentPlanner(workspace).plan(mode="baseline")
    ExperimentDagRunner(workspace).run()
    EnsembleEngine(workspace).search()
    SubmissionPackager(workspace).package_final()
    adapter = FakeKaggleAdapter()

    notebook = KaggleNotebookBridge(workspace, adapter)
    pushed = notebook.push_final()
    job = notebook.run_final(pushed.notebook_ref)
    output = notebook.fetch_output(pushed.notebook_ref)
    submission = SubmissionBridge(workspace, adapter)

    with pytest.raises(RuntimeError, match="explicit confirmation"):
        submission.submit_final(require_confirmation=True, confirmed=False)
    submitted = submission.submit_final(require_confirmation=True, confirmed=True)

    assert pushed.notebook_ref == "azxav/titanic-final"
    assert job.job_id == "job-123"
    assert output.output_path.exists()
    assert submitted.status == "submitted"
    assert (workspace / "kaggle" / "notebooks" / "push_response.json").exists()
    assert (workspace / "kaggle" / "submissions" / "submit_response.json").exists()
    assert adapter.calls == [
        ("push", "solution.ipynb"),
        ("run", "azxav/titanic-final"),
        ("fetch_output", "azxav/titanic-final"),
        ("submit", "titanic"),
    ]


def test_mcp_tools_resources_and_redacted_outputs() -> None:
    workspace = _write_workspace(Path("test-output") / "m5-mcp")
    BaselineExperimentPlanner(workspace).plan(mode="baseline")
    (workspace / "configs" / "competition.yaml").write_text(
        (workspace / "configs" / "competition.yaml").read_text(encoding="utf-8")
        + "\nsecret_hint: KAGGLE_KEY=abc123\n",
        encoding="utf-8",
    )

    assert "competition://current/manifest" in list_resources()
    assert "kgmon.experiment.run" in list_tools()

    run_result = run_tool(
        "kgmon.experiment.run",
        {"workspace": str(workspace), "all": True},
    )
    artifact_result = run_tool("kgmon.artifacts.list", {"workspace": str(workspace)})
    manifest = read_resource("competition://current/manifest", workspace=workspace)

    assert run_result["job_id"].startswith("kgmon-experiment-run-")
    assert run_result["status"] == "completed"
    assert artifact_result["artifacts"][0]["run_id"] == "baseline-sklearn-dummy"
    assert "abc123" not in json.dumps(manifest)
    assert "***" in json.dumps(manifest)
