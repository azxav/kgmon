from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kgmon_kaggle.adapter import KaggleAccessAdapter, KaggleAccessError


class RecordingRunner:
    def __init__(self, stdout: str, returncode: int = 0, stderr: str = "") -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr
        self.commands: list[list[str]] = []

    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        return subprocess.CompletedProcess(
            command,
            self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


def test_adapter_parses_competition_pages_from_vendor_script_output(
) -> None:
    vendor_root = Path("test-output") / "adapter-pages"
    runner = RecordingRunner(
        "\n".join(
            [
                '<untrusted-content source="kaggle-mcp" tool="list_competition_pages">',
                '{"status": "ok", "competition": "titanic", "data": {"pages": [',
                '{"name": "rules", "content": "rules text"},',
                '{"name": "Evaluation", "content": "accuracy"}',
                "]}}",
                "</untrusted-content>",
            ]
        )
    )

    adapter = KaggleAccessAdapter(vendor_root=vendor_root, runner=runner)
    pages = adapter.fetch_competition_pages("titanic")

    assert [(page.name, page.content) for page in pages] == [
        ("rules", "rules text"),
        ("Evaluation", "accuracy"),
    ]
    assert runner.commands[0][-3:] == ["--competition", "titanic", "--pretty"]


def test_adapter_downloads_competition_data_through_kaggle_cli(
) -> None:
    workspace = Path("test-output") / "adapter-download"
    runner = RecordingRunner("downloaded")

    adapter = KaggleAccessAdapter(vendor_root=workspace, runner=runner)
    adapter.download_competition_data("titanic", workspace / "raw")

    assert runner.commands == [
        [
            "kaggle",
            "competitions",
            "download",
            "titanic",
            "--path",
            str(workspace / "raw"),
        ]
    ]


def test_adapter_parses_manifest_when_vendor_prints_pagination_noise() -> None:
    vendor_root = Path("test-output") / "adapter-manifest"
    runner = RecordingRunner(
        "\n".join(
            [
                "Next Page Token = abc123",
                '{"slug": "titanic", "files": [{"name": "train.csv"}]}',
            ]
        )
    )

    adapter = KaggleAccessAdapter(vendor_root=vendor_root, runner=runner)
    manifest = adapter.get_competition_manifest("titanic")

    assert manifest.slug == "titanic"
    assert manifest.files == [{"name": "train.csv"}]


def test_adapter_adds_codex_network_hint_for_sandbox_proxy_failure() -> None:
    runner = RecordingRunner(
        "",
        returncode=1,
        stderr="HTTPSConnectionPool: proxy 127.0.0.1:9 connection refused",
    )

    adapter = KaggleAccessAdapter(vendor_root=Path("test-output"), runner=runner)

    with pytest.raises(KaggleAccessError) as error:
        adapter.download_competition_data("titanic", Path("test-output") / "raw")

    assert "Codex sandbox network access appears blocked" in str(error.value)
