from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from kgmon_cli.main import app
from kgmon_core.profiling import CompetitionProfiler
from kgmon_core.rules import RuleMetricParser
from kgmon_core.validation import ValidationPlanner


def _write_workspace(root: Path) -> Path:
    workspace = root / "competitions" / "titanic"
    shutil.rmtree(root, ignore_errors=True)
    (workspace / "configs").mkdir(parents=True)
    (workspace / "kaggle" / "pages").mkdir(parents=True)
    (workspace / "data" / "raw").mkdir(parents=True)
    (workspace / "data" / "processed").mkdir(parents=True)
    (workspace / "artifacts" / "reports").mkdir(parents=True)

    (workspace / "configs" / "competition.yaml").write_text(
        """competition:
  slug: titanic
  source: kaggle
  task_family: pending
  target_column: null
  id_column: null
  metric:
    name: pending
    direction: maximize
  submission:
    id_column: null
    prediction_columns: []

rules:
  external_data: unknown
  internet_allowed: unknown
  gpu_allowed: true
  auto_submit_allowed: false
  human_review_required: true

data:
  train_path: data/raw/train.csv
  test_path: data/raw/test.csv
  sample_submission_path: data/raw/gender_submission.csv

validation:
  strategy: pending
  group_column: null
  time_column: null
  n_folds: 3
  seed: 42
""",
        encoding="utf-8",
    )
    (workspace / "kaggle" / "pages" / "rules.md").write_text(
        "Participants may not use external data. Internet access is disabled.",
        encoding="utf-8",
    )
    (workspace / "kaggle" / "pages" / "evaluation.md").write_text(
        "Submissions are evaluated on accuracy.",
        encoding="utf-8",
    )
    (workspace / "data" / "raw" / "train.csv").write_text(
        "\n".join(
            [
                "PassengerId,Survived,Name,Fare,Ticket",
                "1,0,A,7.25,111",
                "2,1,B,71.28,222",
                "3,1,C,,333",
                "3,1,C,,333",
                "4,0,D,8.05,444",
                "5,0,E,8.45,555",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (workspace / "data" / "raw" / "test.csv").write_text(
        "\n".join(
            [
                "PassengerId,Name,Fare,Ticket",
                "6,F,9.00,666",
                "7,G,500.00,777",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (workspace / "data" / "raw" / "gender_submission.csv").write_text(
        "PassengerId,Survived\n6,0\n7,1\n",
        encoding="utf-8",
    )
    return workspace


def test_rule_metric_parser_updates_unknown_rules_and_metric() -> None:
    workspace = _write_workspace(Path("test-output") / "m3-parser")

    parsed = RuleMetricParser(workspace).parse_and_update_config()

    assert parsed.metric_name == "accuracy"
    assert parsed.metric_direction == "maximize"
    assert parsed.external_data == "forbidden"
    assert parsed.internet_allowed is False

    config_text = (workspace / "configs" / "competition.yaml").read_text(
        encoding="utf-8"
    )
    assert "name: accuracy" in config_text
    assert "external_data: forbidden" in config_text
    assert "internet_allowed: false" in config_text
    assert "human_review_required: false" in config_text


def test_data_profiler_generates_profile_report_and_updates_config() -> None:
    workspace = _write_workspace(Path("test-output") / "m3-profile")
    RuleMetricParser(workspace).parse_and_update_config()

    result = CompetitionProfiler(workspace).profile()

    assert result.profile_path == workspace / "artifacts" / "reports" / "profile.json"
    payload = json.loads(result.profile_path.read_text(encoding="utf-8"))
    assert payload["task_family"] == "tabular_binary_classification"
    assert payload["target_column"] == "Survived"
    assert payload["id_column"] == "PassengerId"
    assert payload["rows"]["train"] == 6
    assert payload["missing_values"]["train"]["Fare"] == 2
    assert payload["duplicates"]["train_full_rows"] == 1
    assert payload["target_distribution"] == {"0": 3, "1": 3}
    assert payload["train_test_drift"]["Fare"]["mean_abs_diff"] > 200
    assert result.report_path.read_text(encoding="utf-8").startswith(
        "# Data Profile"
    )

    config_text = (workspace / "configs" / "competition.yaml").read_text(
        encoding="utf-8"
    )
    assert "task_family: tabular_binary_classification" in config_text
    assert "target_column: Survived" in config_text
    assert "id_column: PassengerId" in config_text
    assert "prediction_columns: [Survived]" in config_text


def test_validation_planner_persists_stratified_folds_and_leakage_report() -> None:
    workspace = _write_workspace(Path("test-output") / "m3-validation")
    RuleMetricParser(workspace).parse_and_update_config()
    CompetitionProfiler(workspace).profile()

    result = ValidationPlanner(workspace).plan()

    assert result.validation_path == workspace / "configs" / "validation.yaml"
    assert result.folds_path == workspace / "data" / "processed" / "folds.csv"
    assert result.strategy == "StratifiedKFold"
    assert result.leakage_blocked is True
    assert "duplicate train rows detected" in result.leakage_warnings

    with result.folds_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 6
    assert sorted({row["fold"] for row in rows}) == ["0", "1", "2"]
    assert rows[0] == {
        "row_index": "0",
        "id": "1",
        "target": "0",
        "fold": "0",
    }

    validation_text = result.validation_path.read_text(encoding="utf-8")
    assert "strategy: StratifiedKFold" in validation_text
    assert "status: blocked" in validation_text
    assert "folds_path: data/processed/folds.csv" in validation_text


def test_m3_cli_profile_and_validation_plan_commands() -> None:
    workspace = _write_workspace(Path("test-output") / "m3-cli")

    runner = CliRunner()
    audit_result = runner.invoke(
        app,
        [
            "competition",
            "audit-rules",
            "--workspace",
            str(workspace),
        ],
    )
    profile_result = runner.invoke(
        app,
        [
            "data",
            "profile",
            "--workspace",
            str(workspace),
        ],
    )
    validation_result = runner.invoke(
        app,
        [
            "validation",
            "plan",
            "--workspace",
            str(workspace),
        ],
    )

    assert audit_result.exit_code == 0
    assert "metric: accuracy" in audit_result.stdout
    assert profile_result.exit_code == 0
    assert "profile.json" in profile_result.stdout
    assert validation_result.exit_code == 1
    assert "Validation blocked" in validation_result.stdout
