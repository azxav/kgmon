from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from kgmon_core.config import read_competition_config, update_competition_config


@dataclass(frozen=True)
class ValidationPlanResult:
    validation_path: Path
    folds_path: Path
    strategy: str
    leakage_blocked: bool
    leakage_warnings: list[str]


class ValidationPlanner:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def plan(self) -> ValidationPlanResult:
        config = read_competition_config(self.workspace)
        profile = _read_profile(self.workspace)
        train_path = self.workspace / str(config["data.train_path"])
        rows = _read_csv_rows(train_path)

        target_column = str(profile.get("target_column") or "")
        id_column = str(profile.get("id_column") or "")
        n_folds = int(config.get("validation.n_folds") or 5)
        strategy = _choose_strategy(profile, target_column)
        assignments = _assign_folds(rows, target_column, n_folds, strategy)
        leakage_warnings = _detect_leakage(rows, id_column, target_column, profile)
        status = "blocked" if leakage_warnings else "ready"

        folds_path = self.workspace / "data" / "processed" / "folds.csv"
        folds_path.parent.mkdir(parents=True, exist_ok=True)
        _write_folds(folds_path, rows, id_column, target_column, assignments)

        validation_path = self.workspace / "configs" / "validation.yaml"
        validation_path.write_text(
            _render_validation_yaml(
                strategy=strategy,
                n_folds=n_folds,
                seed=int(config.get("validation.seed") or 42),
                status=status,
                leakage_warnings=leakage_warnings,
            ),
            encoding="utf-8",
        )
        update_competition_config(self.workspace, {"validation.strategy": strategy})

        return ValidationPlanResult(
            validation_path=validation_path,
            folds_path=folds_path,
            strategy=strategy,
            leakage_blocked=bool(leakage_warnings),
            leakage_warnings=leakage_warnings,
        )


def _read_profile(workspace: Path) -> dict[str, object]:
    profile_path = workspace / "artifacts" / "reports" / "profile.json"
    return cast(
        dict[str, object],
        json.loads(profile_path.read_text(encoding="utf-8")),
    )


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _choose_strategy(profile: dict[str, object], target_column: str) -> str:
    task_family = str(profile.get("task_family") or "")
    schema = profile.get("schema")
    train_schema = schema.get("train", {}) if isinstance(schema, dict) else {}
    if "group" in train_schema or "Group" in train_schema:
        return "GroupKFold"
    if any(column.lower() in {"date", "time", "timestamp"} for column in train_schema):
        return "TimeSeriesSplit"
    if target_column and "classification" in task_family:
        return "StratifiedKFold"
    return "KFold"


def _assign_folds(
    rows: list[dict[str, str]],
    target_column: str,
    n_folds: int,
    strategy: str,
) -> list[int]:
    if n_folds <= 1:
        raise ValueError("validation.n_folds must be greater than 1")
    if strategy == "StratifiedKFold" and target_column:
        by_target: dict[str, list[int]] = defaultdict(list)
        for index, row in enumerate(rows):
            by_target[row.get(target_column, "")].append(index)
        folds = [0] * len(rows)
        for indices in by_target.values():
            for offset, row_index in enumerate(indices):
                folds[row_index] = offset % n_folds
        return folds
    return [index % n_folds for index in range(len(rows))]


def _detect_leakage(
    rows: list[dict[str, str]],
    id_column: str,
    target_column: str,
    profile: dict[str, object],
) -> list[str]:
    warnings: list[str] = []
    duplicates = profile.get("duplicates")
    if isinstance(duplicates, dict) and duplicates.get("train_full_rows", 0) > 0:
        warnings.append("duplicate train rows detected")
    if target_column:
        lowered_target = target_column.lower()
        for column in rows[0] if rows else []:
            lowered = column.lower()
            if column != target_column and lowered_target in lowered:
                warnings.append(f"possible target leakage column: {column}")
    if id_column:
        seen: set[str] = set()
        duplicate_ids = False
        for row in rows:
            value = row.get(id_column, "")
            if value in seen:
                duplicate_ids = True
                break
            seen.add(value)
        if duplicate_ids:
            warnings.append(f"duplicate id values detected in {id_column}")
    return warnings


def _write_folds(
    path: Path,
    rows: list[dict[str, str]],
    id_column: str,
    target_column: str,
    assignments: list[int],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["row_index", "id", "target", "fold"],
        )
        writer.writeheader()
        for index, row in enumerate(rows):
            writer.writerow(
                {
                    "row_index": index,
                    "id": row.get(id_column, ""),
                    "target": row.get(target_column, ""),
                    "fold": assignments[index],
                }
            )


def _render_validation_yaml(
    strategy: str,
    n_folds: int,
    seed: int,
    status: str,
    leakage_warnings: list[str],
) -> str:
    warning_lines = "\n".join(f"  - {warning}" for warning in leakage_warnings)
    if not warning_lines:
        warning_lines = "  []"
    return f"""strategy: {strategy}
group_column: null
time_column: null
n_folds: {n_folds}
seed: {seed}
folds_path: data/processed/folds.csv
status: {status}
leakage_guards:
  target_column: enforced
  sample_submission: enforced
  train_test_duplicates: enforced
  group_time: enforced
  target_encoding: fold_safe_required
warnings:
{warning_lines}
"""
