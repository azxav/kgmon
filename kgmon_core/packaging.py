from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from kgmon_core.config import read_competition_config
from kgmon_core.registry import ArtifactRegistry


@dataclass(frozen=True)
class PackageResult:
    final_dir: Path
    manifest_path: Path
    provenance_path: Path
    report_path: Path


class SubmissionPackager:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def package_final(self) -> PackageResult:
        config = read_competition_config(self.workspace)
        ensemble_config = self.workspace / "artifacts" / "ensembles" / (
            "ensemble_v001.yaml"
        )
        submission_source = self.workspace / "artifacts" / "submissions" / (
            "submission_ensemble_v001.csv"
        )
        if not ensemble_config.exists() or not submission_source.exists():
            raise FileNotFoundError("run ensemble search before packaging final")

        id_column = str(config["competition.submission.id_column"])
        prediction_columns = list(config["competition.submission.prediction_columns"])
        self._validate_submission(submission_source, id_column, prediction_columns)

        final_dir = self.workspace / "artifacts" / "final"
        model_artifacts_dir = final_dir / "model_artifacts"
        final_dir.mkdir(parents=True, exist_ok=True)
        model_artifacts_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(submission_source, final_dir / "submission.csv")
        for model_path in sorted((self.workspace / "artifacts" / "models").glob("*")):
            if model_path.is_file():
                shutil.copy2(model_path, model_artifacts_dir / model_path.name)

        (final_dir / "inference.py").write_text(
            _render_inference_py(),
            encoding="utf-8",
        )
        (final_dir / "solution.ipynb").write_text(
            json.dumps(_solution_notebook(), indent=2),
            encoding="utf-8",
        )
        (final_dir / "requirements.txt").write_text(
            "pandas\nscikit-learn\n",
            encoding="utf-8",
        )
        (final_dir / "environment.yml").write_text(
            "name: kgmon-final\ndependencies:\n  - python>=3.11\n  - pandas\n",
            encoding="utf-8",
        )
        manifest_path = final_dir / "manifest.yaml"
        manifest_path.write_text(
            _render_manifest(config, submission_source.relative_to(self.workspace)),
            encoding="utf-8",
        )
        provenance_path = final_dir / "provenance.json"
        provenance_path.write_text(
            json.dumps(
                {
                    "competition": {"slug": config["competition.slug"]},
                    "ensemble": {
                        "id": "ensemble_v001",
                        "config_path": ensemble_config.relative_to(
                            self.workspace
                        ).as_posix(),
                    },
                    "submission": {
                        "source": submission_source.relative_to(
                            self.workspace
                        ).as_posix(),
                        "final": "artifacts/final/submission.csv",
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        report_path = final_dir / "report.md"
        report_path.write_text(
            "# Final Package\n\n"
            f"- Competition: {config['competition.slug']}\n"
            "- Ensemble: ensemble_v001\n"
            "- Submission: submission.csv\n",
            encoding="utf-8",
        )

        registry = ArtifactRegistry(self.workspace)
        for artifact_type, path in (
            ("final_submission", final_dir / "submission.csv"),
            ("final_manifest", manifest_path),
            ("final_provenance", provenance_path),
            ("final_report", report_path),
        ):
            registry.register_artifact(
                run_id="ensemble_v001",
                artifact_type=artifact_type,
                path=path,
            )

        return PackageResult(
            final_dir=final_dir,
            manifest_path=manifest_path,
            provenance_path=provenance_path,
            report_path=report_path,
        )

    def _validate_submission(
        self,
        path: Path,
        id_column: str,
        prediction_columns: list[str],
    ) -> None:
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        expected_columns = [id_column, *prediction_columns]
        if not rows:
            raise ValueError("submission.csv has no rows")
        if list(rows[0]) != expected_columns:
            raise ValueError("submission.csv columns do not match competition contract")
        for row in rows:
            for column in expected_columns:
                value = row[column]
                if value == "" or value.lower() in {"nan", "inf", "-inf"}:
                    raise ValueError("submission.csv contains invalid values")


def _render_inference_py() -> str:
    return '''from __future__ import annotations

from pathlib import Path


def predict() -> Path:
    """Return the packaged submission path."""
    return Path(__file__).with_name("submission.csv")
'''


def _solution_notebook() -> dict[str, object]:
    return {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": ["# KGMON Final Solution\\n"],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "from pathlib import Path\\n",
                    "Path('submission.csv').read_text()[:200]\\n",
                ],
            },
        ],
        "metadata": {"language_info": {"name": "python"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def _render_manifest(config: dict[str, object], submission_source: Path) -> str:
    raw_prediction_columns = config["competition.submission.prediction_columns"]
    if not isinstance(raw_prediction_columns, list):
        raw_prediction_columns = []
    prediction_columns = ", ".join(
        str(column) for column in raw_prediction_columns
    )
    return f"""competition:
  slug: {config['competition.slug']}
  target_column: {config['competition.target_column']}
submission:
  id_column: {config['competition.submission.id_column']}
  prediction_columns: [{prediction_columns}]
  source: {submission_source.as_posix()}
package:
  inference: inference.py
  notebook: solution.ipynb
  provenance: provenance.json
"""
