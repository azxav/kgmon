from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from kgmon_cli import main
from kgmon_core.bootstrap import BootstrapResult


def test_competition_bootstrap_command_invokes_bootstrapper(monkeypatch) -> None:
    calls: list[tuple[str, Path]] = []

    class FakeBootstrapper:
        def __init__(self, adapter: object, workspace_root: Path) -> None:
            self.workspace_root = workspace_root

        def bootstrap(self, slug: str) -> BootstrapResult:
            calls.append((slug, self.workspace_root))
            workspace = self.workspace_root / "competitions" / slug
            return BootstrapResult(
                slug=slug,
                workspace=workspace,
                config_path=workspace / "configs" / "competition.yaml",
                registry_path=workspace / "artifacts" / "registry.sqlite",
                downloaded_files=3,
                page_count=2,
            )

    monkeypatch.setattr(main, "CompetitionBootstrapper", FakeBootstrapper)

    result = CliRunner().invoke(
        main.app,
        ["competition", "bootstrap", "titanic", "--workspace-root", "test-output/cli"],
    )

    assert result.exit_code == 0
    assert calls == [("titanic", Path("test-output/cli"))]
    assert "competitions/titanic" in result.stdout.replace("\\", "/")
