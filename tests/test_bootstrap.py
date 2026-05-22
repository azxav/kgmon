from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from kgmon_core.bootstrap import (
    BootstrapResult,
    CompetitionBootstrapper,
)
from kgmon_kaggle.adapter import (
    CompetitionManifest,
    CompetitionPage,
    DownloadedFile,
)
from kgmon_kaggle.doctor import CredentialStatus


class FakeKaggleAdapter:
    def check_credentials(self) -> CredentialStatus:
        return CredentialStatus(
            available=True,
            mode="KAGGLE_API_TOKEN",
            redacted_values={"KAGGLE_API_TOKEN": "kg******en"},
        )

    def get_competition_manifest(self, slug: str) -> CompetitionManifest:
        return CompetitionManifest(
            slug=slug,
            url=f"https://www.kaggle.com/competitions/{slug}",
            files=[
                {"name": "train.csv", "size": 100},
                {"name": "test.csv", "size": 50},
                {"name": "gender_submission.csv", "size": 10},
            ],
        )

    def fetch_competition_pages(
        self,
        slug: str,
        pages: list[str] | None = None,
    ) -> list[CompetitionPage]:
        return [
            CompetitionPage(name="rules", content="No external data."),
            CompetitionPage(
                name="Evaluation",
                content="Submissions are scored on accuracy.",
            ),
            CompetitionPage(name="data-description", content="train.csv and test.csv"),
        ]

    def download_competition_data(
        self,
        slug: str,
        output_dir: Path,
    ) -> list[DownloadedFile]:
        output_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            "train.csv": "PassengerId,Survived\n1,0\n2,1\n",
            "test.csv": "PassengerId\n3\n",
            "gender_submission.csv": "PassengerId,Survived\n3,0\n",
        }
        downloaded = []
        for name, content in paths.items():
            path = output_dir / name
            path.write_text(content, encoding="utf-8")
            downloaded.append(DownloadedFile(path=path, size=path.stat().st_size))
        return downloaded


def test_bootstrap_creates_m2_workspace_config_and_registry() -> None:
    workspace_root = Path("test-output") / "bootstrap"
    shutil.rmtree(workspace_root, ignore_errors=True)
    workspace_root.mkdir(parents=True)

    result = CompetitionBootstrapper(
        adapter=FakeKaggleAdapter(),
        workspace_root=workspace_root,
    ).bootstrap("titanic")

    assert result == BootstrapResult(
        slug="titanic",
        workspace=workspace_root / "competitions" / "titanic",
        config_path=workspace_root
        / "competitions"
        / "titanic"
        / "configs"
        / "competition.yaml",
        registry_path=workspace_root
        / "competitions"
        / "titanic"
        / "artifacts"
        / "registry.sqlite",
        downloaded_files=3,
        page_count=3,
    )

    workspace = result.workspace
    assert (workspace / "kaggle" / "pages" / "rules.md").read_text(
        encoding="utf-8"
    ).startswith('<untrusted-content source="kaggle" page="rules">')
    assert (workspace / "data" / "raw" / "train.csv").exists()
    assert "slug: titanic" in result.config_path.read_text(encoding="utf-8")

    with sqlite3.connect(result.registry_path) as connection:
        dataset_rows = connection.execute(
            "select path, rows, columns from datasets"
        ).fetchall()
        artifact_rows = connection.execute(
            "select type, path, hash from artifacts"
        ).fetchall()

    assert dataset_rows == [
        ("data/raw/gender_submission.csv", 1, 2),
        ("data/raw/test.csv", 1, 1),
        ("data/raw/train.csv", 2, 2),
    ]
    assert len(artifact_rows) == 3
    assert {row[0] for row in artifact_rows} == {"raw_data"}
