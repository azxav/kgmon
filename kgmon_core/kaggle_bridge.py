from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from kgmon_core.config import read_competition_config


class NotebookAdapter(Protocol):
    def push_notebook(
        self,
        notebook_path: Path,
        metadata: dict[str, object],
    ) -> str: ...

    def run_notebook(self, notebook_ref: str) -> str: ...

    def download_notebook_output(self, notebook_ref: str, output_dir: Path) -> Path: ...


class SubmissionAdapter(Protocol):
    def submit_predictions(
        self,
        slug: str,
        submission_path: Path,
        message: str,
    ) -> str: ...


@dataclass(frozen=True)
class NotebookPushResult:
    notebook_ref: str
    archive_path: Path


@dataclass(frozen=True)
class NotebookRunResult:
    job_id: str
    archive_path: Path


@dataclass(frozen=True)
class NotebookOutputResult:
    output_path: Path
    archive_path: Path


@dataclass(frozen=True)
class SubmissionResult:
    status: str
    archive_path: Path


class KaggleNotebookBridge:
    def __init__(self, workspace: Path, adapter: NotebookAdapter) -> None:
        self.workspace = workspace
        self.adapter = adapter

    def push_final(self) -> NotebookPushResult:
        notebook_path = self.workspace / "artifacts" / "final" / "solution.ipynb"
        if not notebook_path.exists():
            raise FileNotFoundError("final solution.ipynb is missing")
        config = read_competition_config(self.workspace)
        notebook_ref = self.adapter.push_notebook(
            notebook_path,
            {
                "competition": config["competition.slug"],
                "source": "kgmon",
            },
        )
        archive_path = self.workspace / "kaggle" / "notebooks" / "push_response.json"
        _write_json(
            archive_path,
            {"notebook_ref": notebook_ref, "notebook_path": str(notebook_path.name)},
        )
        return NotebookPushResult(notebook_ref=notebook_ref, archive_path=archive_path)

    def run_final(self, notebook_ref: str) -> NotebookRunResult:
        job_id = self.adapter.run_notebook(notebook_ref)
        archive_path = self.workspace / "kaggle" / "notebooks" / "run_response.json"
        _write_json(archive_path, {"notebook_ref": notebook_ref, "job_id": job_id})
        return NotebookRunResult(job_id=job_id, archive_path=archive_path)

    def fetch_output(self, notebook_ref: str) -> NotebookOutputResult:
        output_dir = self.workspace / "kaggle" / "notebooks" / "outputs"
        output_path = self.adapter.download_notebook_output(notebook_ref, output_dir)
        archive_path = self.workspace / "kaggle" / "notebooks" / "output_response.json"
        _write_json(
            archive_path,
            {
                "notebook_ref": notebook_ref,
                "output_path": output_path.relative_to(self.workspace).as_posix(),
            },
        )
        return NotebookOutputResult(output_path=output_path, archive_path=archive_path)


class SubmissionBridge:
    def __init__(self, workspace: Path, adapter: SubmissionAdapter) -> None:
        self.workspace = workspace
        self.adapter = adapter

    def submit_final(
        self,
        *,
        require_confirmation: bool,
        confirmed: bool = False,
        message: str = "KGMON final package submission",
    ) -> SubmissionResult:
        config = read_competition_config(self.workspace)
        auto_submit_allowed = bool(config.get("rules.auto_submit_allowed", False))
        if require_confirmation and not confirmed and not auto_submit_allowed:
            raise RuntimeError("explicit confirmation is required before submission")

        submission_path = self.workspace / "artifacts" / "final" / "submission.csv"
        if not submission_path.exists():
            raise FileNotFoundError("final submission.csv is missing")

        status = self.adapter.submit_predictions(
            str(config["competition.slug"]),
            submission_path,
            message,
        )
        archive_path = (
            self.workspace / "kaggle" / "submissions" / "submit_response.json"
        )
        _write_json(
            archive_path,
            {
                "status": status,
                "submission_path": submission_path.relative_to(
                    self.workspace
                ).as_posix(),
            },
        )
        return SubmissionResult(status=status, archive_path=archive_path)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
