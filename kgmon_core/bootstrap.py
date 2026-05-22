from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from kgmon_kaggle.adapter import CompetitionManifest, CompetitionPage, DownloadedFile
from kgmon_kaggle.doctor import CredentialStatus


class KaggleAdapter(Protocol):
    def check_credentials(self) -> CredentialStatus: ...

    def get_competition_manifest(self, slug: str) -> CompetitionManifest: ...

    def fetch_competition_pages(
        self,
        slug: str,
        pages: list[str] | None = None,
    ) -> list[CompetitionPage]: ...

    def download_competition_data(
        self,
        slug: str,
        output_dir: Path,
    ) -> list[DownloadedFile]: ...


@dataclass(frozen=True)
class BootstrapResult:
    slug: str
    workspace: Path
    config_path: Path
    registry_path: Path
    downloaded_files: int
    page_count: int


class CompetitionBootstrapper:
    def __init__(
        self,
        adapter: KaggleAdapter,
        workspace_root: Path | None = None,
    ) -> None:
        self.adapter = adapter
        self.workspace_root = workspace_root or Path.cwd()

    def bootstrap(self, slug: str) -> BootstrapResult:
        credentials = self.adapter.check_credentials()
        if not credentials.available:
            raise RuntimeError(
                "Kaggle credentials are required to bootstrap a competition."
            )

        workspace = self.workspace_root / "competitions" / slug
        _create_workspace(workspace)

        manifest = self.adapter.get_competition_manifest(slug)
        pages = self.adapter.fetch_competition_pages(slug)
        _write_pages(workspace / "kaggle" / "pages", pages)

        raw_dir = workspace / "data" / "raw"
        downloaded = self.adapter.download_competition_data(slug, raw_dir)
        config_path = workspace / "configs" / "competition.yaml"
        config_path.write_text(
            _render_competition_config(manifest, downloaded),
            encoding="utf-8",
        )

        registry_path = workspace / "artifacts" / "registry.sqlite"
        _initialize_registry(registry_path)
        _register_raw_files(registry_path, workspace, downloaded)

        return BootstrapResult(
            slug=slug,
            workspace=workspace,
            config_path=config_path,
            registry_path=registry_path,
            downloaded_files=len(downloaded),
            page_count=len(pages),
        )


def _create_workspace(workspace: Path) -> None:
    for relative in (
        "kaggle/pages",
        "kaggle/writeups",
        "kaggle/notebooks",
        "kaggle/submissions",
        "data/raw",
        "data/interim",
        "data/processed",
        "data/external",
        "configs/model_params",
        "src",
        "runs",
        "artifacts/oof",
        "artifacts/test_preds",
        "artifacts/models",
        "artifacts/ensembles",
        "artifacts/submissions",
        "artifacts/final",
        "artifacts/reports",
        "mlruns",
    ):
        (workspace / relative).mkdir(parents=True, exist_ok=True)

    for relative in ("dvc.yaml", "params.yaml", "Makefile", "README.md"):
        path = workspace / relative
        if not path.exists():
            path.write_text("", encoding="utf-8")


def _write_pages(pages_dir: Path, pages: list[CompetitionPage]) -> None:
    for page in pages:
        safe_name = _safe_filename(page.name)
        wrapped = "\n".join(
            [
                f'<untrusted-content source="kaggle" page="{_escape_attr(page.name)}">',
                page.content,
                "</untrusted-content>",
                "",
            ]
        )
        (pages_dir / f"{safe_name}.md").write_text(wrapped, encoding="utf-8")


def _render_competition_config(
    manifest: CompetitionManifest,
    downloaded: list[DownloadedFile],
) -> str:
    file_names = {file.path.name.lower(): file.path for file in downloaded}
    train_path = _config_data_path(file_names.get("train.csv"))
    test_path = _config_data_path(file_names.get("test.csv"))
    sample_path = _config_data_path(
        file_names.get("sample_submission.csv")
        or file_names.get("gender_submission.csv")
    )
    files = "\n".join(
        f"    - name: {file.get('name', '')}\n      size: {file.get('size', 0)}"
        for file in manifest.files
    )
    if not files:
        files = "    []"

    return f"""competition:
  slug: {manifest.slug}
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

kaggle_access:
  provider: shepsci/kaggle-skill
  mcp_endpoint: https://www.kaggle.com/mcp
  credential_mode: KAGGLE_API_TOKEN
  untrusted_content_wrapped: true

rules:
  external_data: unknown
  internet_allowed: unknown
  gpu_allowed: true
  auto_submit_allowed: false
  human_review_required: true

data:
  train_path: {train_path}
  test_path: {test_path}
  sample_submission_path: {sample_path}

validation:
  strategy: pending
  group_column: null
  time_column: null
  n_folds: 5
  seed: 42

resources:
  backend: local
  gpu_required: false
  max_parallel_runs: 2
  max_runtime_hours: 6

metadata:
  url: {manifest.url}
  files:
{files}
"""


def _initialize_registry(registry_path: Path) -> None:
    with sqlite3.connect(registry_path) as connection:
        connection.executescript(
            """
            create table if not exists runs (
                id text primary key,
                competition_slug text not null,
                status text not null,
                started_at text,
                ended_at text,
                metric_name text,
                metric_value real
            );

            create table if not exists artifacts (
                id text primary key,
                run_id text,
                type text not null,
                path text not null,
                hash text not null,
                created_at text not null default current_timestamp
            );

            create table if not exists datasets (
                id text primary key,
                path text not null,
                hash text not null,
                rows integer not null,
                columns integer not null,
                created_at text not null default current_timestamp
            );

            create table if not exists experiments (
                id text primary key,
                spec_path text not null,
                status text not null,
                parent_id text
            );
            """
        )


def _register_raw_files(
    registry_path: Path,
    workspace: Path,
    downloaded: list[DownloadedFile],
) -> None:
    with sqlite3.connect(registry_path) as connection:
        for file in sorted(
            downloaded,
            key=lambda item: _relative_path(workspace, item.path),
        ):
            digest = _sha256(file.path)
            relative = _relative_path(workspace, file.path)
            rows, columns = _csv_shape(file.path)
            identifier = digest[:16]
            connection.execute(
                """
                insert or replace into datasets(id, path, hash, rows, columns)
                values (?, ?, ?, ?, ?)
                """,
                (identifier, relative, digest, rows, columns),
            )
            connection.execute(
                """
                insert or replace into artifacts(id, run_id, type, path, hash)
                values (?, null, ?, ?, ?)
                """,
                (f"raw-{identifier}", "raw_data", relative, digest),
            )


def _csv_shape(path: Path) -> tuple[int, int]:
    if path.suffix.lower() != ".csv":
        return 0, 0

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        rows = sum(1 for _ in reader)
    return rows, len(header)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(workspace: Path, path: Path) -> str:
    return path.relative_to(workspace).as_posix()


def _config_data_path(path: Path | None) -> str:
    if path is None:
        return "null"
    return f"data/raw/{path.name}"


def _safe_filename(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-").lower()
    return safe or "page"


def _escape_attr(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;")
