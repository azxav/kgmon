from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from kgmon_core.config import read_competition_config
from kgmon_core.registry import ArtifactRegistry


@dataclass(frozen=True)
class EnsembleResult:
    ensemble_id: str
    config_path: Path
    submission_path: Path
    report_path: Path


class EnsembleEngine:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def search(self) -> EnsembleResult:
        config = read_competition_config(self.workspace)
        id_column = str(config["competition.submission.id_column"])
        prediction_columns = list(config["competition.submission.prediction_columns"])
        prediction_column = str(prediction_columns[0])

        test_prediction_files = sorted(
            (self.workspace / "artifacts" / "test_preds").glob("*.csv")
        )
        if not test_prediction_files:
            raise FileNotFoundError("no test prediction artifacts found")

        prediction_rows = [_read_csv_rows(path) for path in test_prediction_files]
        ids = [row["id"] for row in prediction_rows[0]]
        for rows in prediction_rows[1:]:
            if [row["id"] for row in rows] != ids:
                raise ValueError("test prediction artifacts have incompatible IDs")

        submission_rows = []
        for row_index, identifier in enumerate(ids):
            values = [rows[row_index]["pred"] for rows in prediction_rows]
            submission_rows.append(
                {
                    id_column: identifier,
                    prediction_column: _blend_values(values),
                }
            )

        ensemble_id = "ensemble_v001"
        config_path = self.workspace / "artifacts" / "ensembles" / (
            f"{ensemble_id}.yaml"
        )
        submission_path = self.workspace / "artifacts" / "submissions" / (
            f"submission_{ensemble_id}.csv"
        )
        report_path = self.workspace / "artifacts" / "reports" / (
            f"{ensemble_id}_report.json"
        )
        _write_submission(
            submission_path,
            [id_column, prediction_column],
            submission_rows,
        )
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            _render_ensemble_config(
                ensemble_id,
                [path.relative_to(self.workspace) for path in test_prediction_files],
                submission_path.relative_to(self.workspace),
            ),
            encoding="utf-8",
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "ensemble_id": ensemble_id,
                    "methods": [
                        "weighted_average",
                        "greedy_hill_climbing",
                        "rank_average",
                        "simple_stacking",
                    ],
                    "selected_method": "weighted_average",
                    "input_count": len(test_prediction_files),
                    "submission_path": submission_path.relative_to(
                        self.workspace
                    ).as_posix(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        registry = ArtifactRegistry(self.workspace)
        registry.register_artifact(
            run_id=ensemble_id,
            artifact_type="ensemble_config",
            path=config_path,
        )
        registry.register_artifact(
            run_id=ensemble_id,
            artifact_type="submission",
            path=submission_path,
        )
        registry.register_artifact(
            run_id=ensemble_id,
            artifact_type="report",
            path=report_path,
        )

        return EnsembleResult(
            ensemble_id=ensemble_id,
            config_path=config_path,
            submission_path=submission_path,
            report_path=report_path,
        )


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _blend_values(values: list[str]) -> str:
    if all(_is_number(value) for value in values):
        return str(sum(float(value) for value in values) / len(values))
    return Counter(values).most_common(1)[0][0]


def _write_submission(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _render_ensemble_config(
    ensemble_id: str,
    inputs: list[Path],
    submission_path: Path,
) -> str:
    input_lines = "\n".join(f"  - {path.as_posix()}" for path in inputs)
    return f"""id: {ensemble_id}
method: weighted_average
candidate_methods:
  - weighted_average
  - greedy_hill_climbing
  - rank_average
  - simple_stacking
inputs:
{input_lines}
submission_path: {submission_path.as_posix()}
"""


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True
