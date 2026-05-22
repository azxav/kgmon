from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RegisteredArtifact:
    run_id: str | None
    type: str
    path: str
    hash: str


class ArtifactRegistry:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.path = workspace / "artifacts" / "registry.sqlite"

    def ensure(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
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

    def register_run(
        self,
        *,
        run_id: str,
        competition_slug: str,
        status: str,
        metric_name: str,
        metric_value: float,
    ) -> None:
        self.ensure()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                insert or replace into runs(
                    id, competition_slug, status, started_at, ended_at,
                    metric_name, metric_value
                )
                values (?, ?, ?, current_timestamp, current_timestamp, ?, ?)
                """,
                (run_id, competition_slug, status, metric_name, metric_value),
            )

    def register_experiment(
        self,
        *,
        experiment_id: str,
        spec_path: Path,
        status: str,
        parent_id: str | None = None,
    ) -> None:
        self.ensure()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                insert or replace into experiments(id, spec_path, status, parent_id)
                values (?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    _relative_path(self.workspace, spec_path),
                    status,
                    parent_id,
                ),
            )

    def register_artifact(
        self,
        *,
        run_id: str | None,
        artifact_type: str,
        path: Path,
    ) -> None:
        self.ensure()
        digest = _sha256(path)
        relative = _relative_path(self.workspace, path)
        identifier = f"{artifact_type}-{digest[:16]}"
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                insert or replace into artifacts(id, run_id, type, path, hash)
                values (?, ?, ?, ?, ?)
                """,
                (identifier, run_id, artifact_type, relative, digest),
            )

    def list_artifacts(self) -> list[RegisteredArtifact]:
        self.ensure()
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                """
                select run_id, type, path, hash
                from artifacts
                order by run_id is null, run_id, type, path
                """
            ).fetchall()
        return [
            RegisteredArtifact(
                run_id=row[0],
                type=row[1],
                path=row[2],
                hash=row[3],
            )
            for row in rows
        ]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(workspace: Path, path: Path) -> str:
    return path.relative_to(workspace).as_posix()
