from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TrackingRun:
    run_id: str
    path: Path


class MLflowTrackingAdapter:
    """Small MLflow-compatible adapter with a local JSON fallback."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.run: TrackingRun | None = None
        self.params: dict[str, Any] = {}
        self.metrics: dict[str, float] = {}
        self.artifacts: list[str] = []

    def start_run(self, run_name: str) -> TrackingRun:
        run_path = self.workspace / "mlruns" / run_name
        run_path.mkdir(parents=True, exist_ok=True)
        self.run = TrackingRun(run_id=run_name, path=run_path)
        self._flush()
        return self.run

    def log_params(self, params: dict[str, Any]) -> None:
        self.params.update(params)
        self._flush()

    def log_metrics(self, metrics: dict[str, float]) -> None:
        self.metrics.update(metrics)
        self._flush()

    def log_artifact(self, path: Path) -> None:
        self.artifacts.append(path.relative_to(self.workspace).as_posix())
        self._flush()

    def register_model(self, model_path: Path) -> None:
        self.log_artifact(model_path)

    def _flush(self) -> None:
        if self.run is None:
            return
        payload = {
            "run_id": self.run.run_id,
            "params": self.params,
            "metrics": self.metrics,
            "artifacts": self.artifacts,
        }
        (self.run.path / "tracking.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
