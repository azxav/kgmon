from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from math import sqrt
from pathlib import Path
from typing import Protocol

from kgmon_core.config import read_competition_config
from kgmon_core.registry import ArtifactRegistry
from kgmon_core.tracking import MLflowTrackingAdapter

BASELINE_RUN_ID = "baseline-sklearn-dummy"
BASELINE_SPEC_NAME = "baseline_sklearn_dummy.yaml"
BASELINE_FEATURE_SET = "tabular_basic"
BASELINE_MODEL_FAMILY = "sklearn"


class BaselineModel(Protocol):
    def predict(self, rows: list[dict[str, str]]) -> list[str]: ...


class BaselineTrainer(Protocol):
    model_family: str

    def fit(
        self,
        rows: list[dict[str, str]],
        target_column: str,
        task_family: str,
    ) -> BaselineModel: ...


@dataclass(frozen=True)
class ExperimentPlanResult:
    experiments_path: Path
    spec_paths: list[Path]


@dataclass(frozen=True)
class ExperimentRunResult:
    run_id: str
    status: str
    metric_name: str
    metric_value: float
    oof_path: Path
    test_predictions_path: Path
    model_path: Path
    report_path: Path


@dataclass(frozen=True)
class DagRunResult:
    completed: list[str]
    failed: list[str]


@dataclass(frozen=True)
class DummyBaselineModel:
    prediction: str

    def predict(self, rows: list[dict[str, str]]) -> list[str]:
        return [self.prediction for _ in rows]


class SklearnBaselineTrainer:
    """Small sklearn-style dummy baseline without a hard sklearn dependency."""

    model_family = BASELINE_MODEL_FAMILY

    def fit(
        self,
        rows: list[dict[str, str]],
        target_column: str,
        task_family: str,
    ) -> BaselineModel:
        values = [row[target_column] for row in rows if row.get(target_column) != ""]
        if not values:
            return DummyBaselineModel(prediction="")
        if "regression" in task_family and all(_is_number(value) for value in values):
            mean_value = sum(float(value) for value in values) / len(values)
            return DummyBaselineModel(prediction=str(mean_value))
        return DummyBaselineModel(prediction=Counter(values).most_common(1)[0][0])


class _MissingOptionalDependencyTrainer:
    model_family: str
    dependency_name: str

    def fit(
        self,
        rows: list[dict[str, str]],
        target_column: str,
        task_family: str,
    ) -> BaselineModel:
        raise RuntimeError(
            f"{self.model_family} trainer requires optional dependency "
            f"{self.dependency_name}."
        )


class LightGBMTrainer(_MissingOptionalDependencyTrainer):
    model_family = "lightgbm"
    dependency_name = "lightgbm"


class XGBoostTrainer(_MissingOptionalDependencyTrainer):
    model_family = "xgboost"
    dependency_name = "xgboost"


class CatBoostTrainer(_MissingOptionalDependencyTrainer):
    model_family = "catboost"
    dependency_name = "catboost"


class BaselineExperimentPlanner:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def plan(self, mode: str = "baseline") -> ExperimentPlanResult:
        if mode != "baseline":
            raise ValueError("only baseline experiment planning is implemented")

        configs_dir = self.workspace / "configs"
        spec_dir = configs_dir / "model_params"
        spec_dir.mkdir(parents=True, exist_ok=True)
        spec_path = spec_dir / BASELINE_SPEC_NAME
        spec_path.write_text(_render_baseline_spec(), encoding="utf-8")

        experiments_path = configs_dir / "experiments.yaml"
        experiments_path.write_text(
            _render_experiments_yaml(spec_path.relative_to(self.workspace)),
            encoding="utf-8",
        )
        return ExperimentPlanResult(
            experiments_path=experiments_path,
            spec_paths=[spec_path],
        )


class BaselineExperimentRunner:
    def __init__(
        self,
        workspace: Path,
        trainer: BaselineTrainer | None = None,
    ) -> None:
        self.workspace = workspace
        self.trainer = trainer or SklearnBaselineTrainer()

    def run_all(self) -> ExperimentRunResult:
        _require_ready_validation(self.workspace)
        spec_path = self.workspace / "configs" / "model_params" / BASELINE_SPEC_NAME
        if not spec_path.exists():
            raise FileNotFoundError(
                "baseline experiment spec is missing; run experiment plan first"
            )

        config = read_competition_config(self.workspace)
        train_path = self.workspace / str(config["data.train_path"])
        test_path = self.workspace / str(config["data.test_path"])
        folds_path = self.workspace / "data" / "processed" / "folds.csv"
        train_rows = _read_csv_rows(train_path)
        test_rows = _read_csv_rows(test_path)
        folds = _read_folds(folds_path)
        target_column = str(config["competition.target_column"])
        id_column = str(config["competition.id_column"])
        task_family = str(config["competition.task_family"])
        metric_name = str(config["competition.metric.name"])

        oof_rows: list[dict[str, str]] = []
        predictions_by_index: dict[int, str] = {}
        for fold in sorted({assignment.fold for assignment in folds.values()}):
            fit_rows = [
                row
                for index, row in enumerate(train_rows)
                if folds[index].fold != fold
            ]
            predict_indices = [
                index for index in range(len(train_rows)) if folds[index].fold == fold
            ]
            model = self.trainer.fit(fit_rows, target_column, task_family)
            predict_rows = [train_rows[index] for index in predict_indices]
            predictions = model.predict(predict_rows)
            for row_index, prediction in zip(predict_indices, predictions, strict=True):
                predictions_by_index[row_index] = prediction

        for index, row in enumerate(train_rows):
            prediction = predictions_by_index[index]
            oof_rows.append(
                {
                    "id": row.get(id_column, ""),
                    "fold": str(folds[index].fold),
                    "y_true": row.get(target_column, ""),
                    "pred": prediction,
                    "run_id": BASELINE_RUN_ID,
                    "model_family": self.trainer.model_family,
                    "feature_set": BASELINE_FEATURE_SET,
                }
            )

        final_model = self.trainer.fit(train_rows, target_column, task_family)
        test_predictions = final_model.predict(test_rows)
        test_prediction_rows = [
            {
                "id": row.get(id_column, ""),
                "pred": prediction,
                "run_id": BASELINE_RUN_ID,
                "model_family": self.trainer.model_family,
                "feature_set": BASELINE_FEATURE_SET,
            }
            for row, prediction in zip(test_rows, test_predictions, strict=True)
        ]

        metric_value = _score(metric_name, oof_rows)
        oof_path = self.workspace / "artifacts" / "oof" / f"{BASELINE_RUN_ID}.csv"
        test_predictions_path = (
            self.workspace
            / "artifacts"
            / "test_preds"
            / f"{BASELINE_RUN_ID}.csv"
        )
        model_path = (
            self.workspace / "artifacts" / "models" / f"{BASELINE_RUN_ID}.json"
        )
        report_path = (
            self.workspace / "runs" / BASELINE_RUN_ID / "run_report.json"
        )
        _write_dict_rows(
            oof_path,
            ["id", "fold", "y_true", "pred", "run_id", "model_family", "feature_set"],
            oof_rows,
        )
        _write_dict_rows(
            test_predictions_path,
            ["id", "pred", "run_id", "model_family", "feature_set"],
            test_prediction_rows,
        )
        _write_model_artifact(model_path, final_model, task_family)
        _write_run_report(
            report_path,
            metric_name=metric_name,
            metric_value=metric_value,
            oof_path=oof_path.relative_to(self.workspace),
            test_predictions_path=test_predictions_path.relative_to(self.workspace),
            model_path=model_path.relative_to(self.workspace),
        )

        registry = ArtifactRegistry(self.workspace)
        registry.register_run(
            run_id=BASELINE_RUN_ID,
            competition_slug=str(config["competition.slug"]),
            status="completed",
            metric_name=metric_name,
            metric_value=metric_value,
        )
        registry.register_experiment(
            experiment_id=BASELINE_RUN_ID,
            spec_path=spec_path,
            status="completed",
        )
        for artifact_type, artifact_path in (
            ("oof_predictions", oof_path),
            ("test_predictions", test_predictions_path),
            ("model", model_path),
            ("report", report_path),
        ):
            registry.register_artifact(
                run_id=BASELINE_RUN_ID,
                artifact_type=artifact_type,
                path=artifact_path,
            )

        tracking = MLflowTrackingAdapter(self.workspace)
        tracking.start_run(BASELINE_RUN_ID)
        tracking.log_params(
            {
                "model_family": self.trainer.model_family,
                "feature_set": BASELINE_FEATURE_SET,
                "task_family": task_family,
            }
        )
        tracking.log_metrics({metric_name: metric_value})
        tracking.log_artifact(oof_path)
        tracking.log_artifact(test_predictions_path)
        tracking.register_model(model_path)

        return ExperimentRunResult(
            run_id=BASELINE_RUN_ID,
            status="completed",
            metric_name=metric_name,
            metric_value=metric_value,
            oof_path=oof_path,
            test_predictions_path=test_predictions_path,
            model_path=model_path,
            report_path=report_path,
        )


class ExperimentDagRunner:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def run(self, dag_path: Path | None = None) -> DagRunResult:
        selected_path = dag_path or self._default_dag_path()
        nodes = _read_dag_nodes(selected_path) if selected_path.exists() else []
        if not nodes:
            nodes = [
                DagNode(
                    id=BASELINE_RUN_ID,
                    spec_path=self.workspace
                    / "configs"
                    / "model_params"
                    / BASELINE_SPEC_NAME,
                    depends_on=[],
                    retry=0,
                )
            ]

        completed: list[str] = []
        failed: list[str] = []
        for node in _dependency_order(nodes):
            try:
                if node.id != BASELINE_RUN_ID:
                    raise ValueError(f"unsupported experiment node: {node.id}")
                BaselineExperimentRunner(self.workspace).run_all()
                completed.append(node.id)
            except Exception:
                failed.append(node.id)
                if node.retry <= 0:
                    continue
                try:
                    BaselineExperimentRunner(self.workspace).run_all()
                    failed.remove(node.id)
                    completed.append(node.id)
                except Exception:
                    pass
        return DagRunResult(completed=completed, failed=failed)

    def _default_dag_path(self) -> Path:
        dag_path = self.workspace / "configs" / "experiments" / "baseline_dag.yaml"
        if dag_path.exists():
            return dag_path
        return self.workspace / "configs" / "experiments.yaml"


@dataclass(frozen=True)
class DagNode:
    id: str
    spec_path: Path
    depends_on: list[str]
    retry: int = 0


@dataclass(frozen=True)
class FoldAssignment:
    fold: int


def _read_dag_nodes(path: Path) -> list[DagNode]:
    nodes: list[DagNode] = []
    current: dict[str, str] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("- id:"):
            if current is not None:
                nodes.append(_dag_node_from_mapping(path, current))
            current = {"id": stripped.split(":", 1)[1].strip()}
        elif current is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            current[key.strip()] = value.strip()
    if current is not None:
        nodes.append(_dag_node_from_mapping(path, current))
    return nodes


def _dag_node_from_mapping(path: Path, mapping: dict[str, str]) -> DagNode:
    workspace = (
        path.parents[2] if path.parent.name == "experiments" else path.parents[1]
    )
    spec_value = mapping.get("spec_path", "")
    return DagNode(
        id=mapping["id"],
        spec_path=workspace / spec_value,
        depends_on=_parse_inline_list(mapping.get("depends_on", "[]")),
        retry=int(mapping.get("retry", "0") or 0),
    )


def _dependency_order(nodes: list[DagNode]) -> list[DagNode]:
    by_id = {node.id: node for node in nodes}
    ordered: list[DagNode] = []
    temporary: set[str] = set()
    permanent: set[str] = set()

    def visit(node: DagNode) -> None:
        if node.id in permanent:
            return
        if node.id in temporary:
            raise ValueError(f"cycle detected in experiment DAG at {node.id}")
        temporary.add(node.id)
        for dependency in node.depends_on:
            if dependency in by_id:
                visit(by_id[dependency])
        temporary.remove(node.id)
        permanent.add(node.id)
        ordered.append(node)

    for node in nodes:
        visit(node)
    return ordered


def _parse_inline_list(value: str) -> list[str]:
    stripped = value.strip()
    if stripped == "[]":
        return []
    if stripped.startswith("[") and stripped.endswith("]"):
        inner = stripped[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("'\"") for item in inner.split(",")]
    return [stripped] if stripped else []


def _render_baseline_spec() -> str:
    return f"""id: {BASELINE_RUN_ID}
trainer: sklearn_dummy
model_family: {BASELINE_MODEL_FAMILY}
feature_set: {BASELINE_FEATURE_SET}
status: planned
outputs:
  oof_contract: id | fold | y_true | pred | run_id | model_family | feature_set
  test_prediction_contract: id | pred | run_id | model_family | feature_set
"""


def _render_experiments_yaml(spec_path: Path) -> str:
    return f"""mode: baseline
status: planned
experiments:
  - id: {BASELINE_RUN_ID}
    spec_path: {spec_path.as_posix()}
    status: planned
"""


def _require_ready_validation(workspace: Path) -> None:
    validation_path = workspace / "configs" / "validation.yaml"
    if not validation_path.exists():
        raise FileNotFoundError("validation.yaml is required before experiments run")
    validation_text = validation_path.read_text(encoding="utf-8")
    if "status: ready" not in validation_text:
        raise RuntimeError("experiments are blocked until validation status is ready")


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_folds(path: Path) -> dict[int, FoldAssignment]:
    rows = _read_csv_rows(path)
    return {
        int(row["row_index"]): FoldAssignment(fold=int(row["fold"]))
        for row in rows
    }


def _write_dict_rows(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_model_artifact(
    path: Path,
    model: BaselineModel,
    task_family: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": BASELINE_RUN_ID,
        "model_family": BASELINE_MODEL_FAMILY,
        "feature_set": BASELINE_FEATURE_SET,
        "task_family": task_family,
        "model": {
            "type": "dummy_baseline",
            "prediction": getattr(model, "prediction", ""),
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_run_report(
    path: Path,
    *,
    metric_name: str,
    metric_value: float,
    oof_path: Path,
    test_predictions_path: Path,
    model_path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": BASELINE_RUN_ID,
        "status": "completed",
        "metric": {"name": metric_name, "value": metric_value},
        "artifacts": {
            "oof": oof_path.as_posix(),
            "test_predictions": test_predictions_path.as_posix(),
            "model": model_path.as_posix(),
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _score(metric_name: str, oof_rows: list[dict[str, str]]) -> float:
    if metric_name == "accuracy":
        if not oof_rows:
            return 0.0
        correct = sum(1 for row in oof_rows if row["y_true"] == row["pred"])
        return correct / len(oof_rows)
    if metric_name == "mae":
        errors = [
            abs(float(row["y_true"]) - float(row["pred"]))
            for row in oof_rows
            if _is_number(row["y_true"]) and _is_number(row["pred"])
        ]
        return sum(errors) / len(errors) if errors else 0.0
    if metric_name in {"rmse", "rmsle"}:
        errors = [
            (float(row["y_true"]) - float(row["pred"])) ** 2
            for row in oof_rows
            if _is_number(row["y_true"]) and _is_number(row["pred"])
        ]
        return sqrt(sum(errors) / len(errors)) if errors else 0.0
    return 0.0


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True
