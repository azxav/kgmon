from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kgmon_cli.main import app
from kgmon_core.experiments import (
    BaselineExperimentPlanner,
    BaselineExperimentRunner,
    CatBoostTrainer,
    LightGBMTrainer,
    XGBoostTrainer,
)


def _write_workspace(root: Path) -> Path:
    workspace = root / "competitions" / "titanic"
    shutil.rmtree(root, ignore_errors=True)
    (workspace / "configs").mkdir(parents=True)
    (workspace / "data" / "raw").mkdir(parents=True)
    (workspace / "data" / "processed").mkdir(parents=True)
    (workspace / "artifacts" / "reports").mkdir(parents=True)

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
    (workspace / "artifacts" / "reports" / "profile.json").write_text(
        json.dumps(
            {
                "task_family": "tabular_binary_classification",
                "target_column": "Survived",
                "id_column": "PassengerId",
            }
        ),
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
        "\n".join(
            [
                "PassengerId,Name,Fare",
                "7,G,9.00",
                "8,H,500.00",
            ]
        )
        + "\n",
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


def test_baseline_experiment_planner_writes_immutable_baseline_spec() -> None:
    workspace = _write_workspace(Path("test-output") / "m4-plan")

    result = BaselineExperimentPlanner(workspace).plan(mode="baseline")

    assert result.experiments_path == workspace / "configs" / "experiments.yaml"
    assert result.spec_paths == [
        workspace / "configs" / "model_params" / "baseline_sklearn_dummy.yaml"
    ]
    spec_text = result.spec_paths[0].read_text(encoding="utf-8")
    assert "id: baseline-sklearn-dummy" in spec_text
    assert "trainer: sklearn_dummy" in spec_text
    assert "model_family: sklearn" in spec_text
    assert "feature_set: tabular_basic" in spec_text


def test_baseline_experiment_runner_writes_oof_test_model_and_run_contracts() -> None:
    workspace = _write_workspace(Path("test-output") / "m4-run")
    BaselineExperimentPlanner(workspace).plan(mode="baseline")

    result = BaselineExperimentRunner(workspace).run_all()

    assert result.run_id == "baseline-sklearn-dummy"
    assert result.status == "completed"
    assert result.metric_name == "accuracy"
    assert 0.0 <= result.metric_value <= 1.0

    with result.oof_path.open(newline="", encoding="utf-8") as handle:
        oof_rows = list(csv.DictReader(handle))
    assert list(oof_rows[0]) == [
        "id",
        "fold",
        "y_true",
        "pred",
        "run_id",
        "model_family",
        "feature_set",
    ]
    assert len(oof_rows) == 6
    assert {row["run_id"] for row in oof_rows} == {"baseline-sklearn-dummy"}
    assert {row["model_family"] for row in oof_rows} == {"sklearn"}

    with result.test_predictions_path.open(newline="", encoding="utf-8") as handle:
        test_rows = list(csv.DictReader(handle))
    assert list(test_rows[0]) == [
        "id",
        "pred",
        "run_id",
        "model_family",
        "feature_set",
    ]
    assert [row["id"] for row in test_rows] == ["7", "8"]
    assert result.model_path.read_text(encoding="utf-8").startswith("{")


def test_gbdt_adapters_report_missing_optional_dependencies() -> None:
    for trainer_class in (LightGBMTrainer, XGBoostTrainer, CatBoostTrainer):
        trainer = trainer_class()
        with pytest.raises(RuntimeError, match="optional dependency"):
            trainer.fit([], "Survived", "tabular_binary_classification")


def test_m4_cli_plan_and_run_commands() -> None:
    workspace = _write_workspace(Path("test-output") / "m4-cli")
    runner = CliRunner()

    plan_result = runner.invoke(
        app,
        [
            "experiment",
            "plan",
            "--mode",
            "baseline",
            "--workspace",
            str(workspace),
        ],
    )
    run_result = runner.invoke(
        app,
        [
            "experiment",
            "run",
            "--all",
            "--workspace",
            str(workspace),
        ],
    )

    assert plan_result.exit_code == 0
    assert "baseline-sklearn-dummy" in plan_result.stdout
    assert run_result.exit_code == 0
    assert "OOF predictions" in run_result.stdout
    assert "test predictions" in run_result.stdout
