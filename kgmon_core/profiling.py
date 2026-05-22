from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from kgmon_core.config import (
    read_competition_config,
    update_competition_config,
)


@dataclass(frozen=True)
class ProfileResult:
    profile_path: Path
    report_path: Path
    task_family: str
    target_column: str | None
    id_column: str | None


class CompetitionProfiler:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def profile(self) -> ProfileResult:
        config = read_competition_config(self.workspace)
        train_path = self.workspace / str(config["data.train_path"])
        test_path = self.workspace / str(config["data.test_path"])
        sample_path = self.workspace / str(config["data.sample_submission_path"])

        train_rows = _read_csv_rows(train_path)
        test_rows = _read_csv_rows(test_path)
        sample_rows = _read_csv_rows(sample_path)
        train_columns = list(train_rows[0].keys()) if train_rows else []
        test_columns = list(test_rows[0].keys()) if test_rows else []
        sample_columns = list(sample_rows[0].keys()) if sample_rows else []

        target_column = _infer_target_column(
            train_columns,
            test_columns,
            sample_columns,
        )
        id_column = _infer_id_column(train_columns, test_columns, sample_columns)
        task_family = _infer_task_family(train_rows, target_column)
        profile = {
            "task_family": task_family,
            "target_column": target_column,
            "id_column": id_column,
            "rows": {"train": len(train_rows), "test": len(test_rows)},
            "columns": {"train": train_columns, "test": test_columns},
            "schema": {
                "train": _schema(train_rows),
                "test": _schema(test_rows),
            },
            "missing_values": {
                "train": _missing_counts(train_rows),
                "test": _missing_counts(test_rows),
            },
            "duplicates": {
                "train_full_rows": _duplicate_full_rows(train_rows),
                "test_full_rows": _duplicate_full_rows(test_rows),
            },
            "target_distribution": _target_distribution(train_rows, target_column),
            "train_test_drift": _numeric_train_test_drift(
                train_rows,
                test_rows,
                exclude={column for column in (id_column, target_column) if column},
            ),
        }

        reports_dir = self.workspace / "artifacts" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        profile_path = reports_dir / "profile.json"
        report_path = reports_dir / "profile.md"
        profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")
        report_path.write_text(_render_profile_report(profile), encoding="utf-8")

        replacements = {
            "competition.task_family": task_family,
            "competition.target_column": target_column or "null",
            "competition.id_column": id_column or "null",
            "competition.submission.id_column": id_column or "null",
        }
        if target_column is not None:
            replacements["competition.submission.prediction_columns"] = (
                f"[{target_column}]"
            )
        update_competition_config(self.workspace, replacements)

        return ProfileResult(
            profile_path=profile_path,
            report_path=report_path,
            task_family=task_family,
            target_column=target_column,
            id_column=id_column,
        )


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _infer_target_column(
    train_columns: list[str],
    test_columns: list[str],
    sample_columns: list[str],
) -> str | None:
    candidates = [
        column
        for column in train_columns
        if column not in test_columns and column in sample_columns
    ]
    if candidates:
        return candidates[0]
    for name in ("target", "label", "y"):
        for column in train_columns:
            if column.lower() == name:
                return column
    return None


def _infer_id_column(
    train_columns: list[str],
    test_columns: list[str],
    sample_columns: list[str],
) -> str | None:
    shared = [column for column in train_columns if column in test_columns]
    sample_first = sample_columns[0] if sample_columns else None
    if sample_first in shared:
        return sample_first
    for column in shared:
        lowered = column.lower()
        if lowered == "id" or lowered.endswith("id"):
            return column
    return shared[0] if shared else None


def _infer_task_family(
    rows: list[dict[str, str]],
    target_column: str | None,
) -> str:
    if target_column is None:
        return "tabular_unknown"
    values = [
        row[target_column]
        for row in rows
        if row.get(target_column) not in {"", None}
    ]
    unique = set(values)
    if len(unique) == 2:
        return "tabular_binary_classification"
    if values and all(_is_number(value) for value in values) and len(unique) > 20:
        return "tabular_regression"
    return "tabular_multiclass_classification"


def _schema(rows: list[dict[str, str]]) -> dict[str, str]:
    if not rows:
        return {}
    schema = {}
    for column in rows[0]:
        values = [row[column] for row in rows if row.get(column) not in {"", None}]
        if values and all(_is_number(value) for value in values):
            schema[column] = "numeric"
        else:
            schema[column] = "categorical"
    return schema


def _missing_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    if not rows:
        return {}
    return {
        column: sum(1 for row in rows if row.get(column, "") == "")
        for column in rows[0]
    }


def _duplicate_full_rows(rows: list[dict[str, str]]) -> int:
    counts = Counter(tuple(row.items()) for row in rows)
    return sum(count - 1 for count in counts.values() if count > 1)


def _target_distribution(
    rows: list[dict[str, str]],
    target_column: str | None,
) -> dict[str, int]:
    if target_column is None:
        return {}
    return dict(Counter(row[target_column] for row in rows))


def _numeric_train_test_drift(
    train_rows: list[dict[str, str]],
    test_rows: list[dict[str, str]],
    exclude: set[str],
) -> dict[str, dict[str, float]]:
    if not train_rows or not test_rows:
        return {}
    drift = {}
    for column in train_rows[0]:
        if column in exclude or column not in test_rows[0]:
            continue
        train_values = _numeric_values(train_rows, column)
        test_values = _numeric_values(test_rows, column)
        if not train_values or not test_values:
            continue
        train_mean = mean(train_values)
        test_mean = mean(test_values)
        drift[column] = {
            "train_mean": train_mean,
            "test_mean": test_mean,
            "mean_abs_diff": abs(train_mean - test_mean),
        }
    return drift


def _numeric_values(rows: list[dict[str, str]], column: str) -> list[float]:
    values = []
    for row in rows:
        value = row.get(column, "")
        if value != "" and _is_number(value):
            values.append(float(value))
    return values


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _render_profile_report(profile: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Data Profile",
            "",
            f"- task_family: {profile['task_family']}",
            f"- target_column: {profile['target_column']}",
            f"- id_column: {profile['id_column']}",
            f"- train_rows: {profile['rows']['train']}",
            f"- test_rows: {profile['rows']['test']}",
            f"- duplicate_train_rows: {profile['duplicates']['train_full_rows']}",
            "",
        ]
    )
