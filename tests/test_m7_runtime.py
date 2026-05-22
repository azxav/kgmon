from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from typer.testing import CliRunner

from kgmon_kaggle.adapter import CompetitionManifest, CompetitionPage, DownloadedFile
from kgmon_kaggle.doctor import CredentialStatus
from kgmon_runtime.events import EventBus, EventType
from kgmon_runtime.hooks import HookDefinition, HookRunner
from kgmon_runtime.setup import RuntimeSetup
from kgx_cli import main as kgx_main


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
            CompetitionPage(name="overview", content="Titanic starter page."),
        ]

    def download_competition_data(
        self,
        slug: str,
        output_dir: Path,
    ) -> list[DownloadedFile]:
        output_dir.mkdir(parents=True, exist_ok=True)
        files = {
            "train.csv": "PassengerId,Survived\n1,0\n2,1\n",
            "test.csv": "PassengerId\n3\n",
            "gender_submission.csv": "PassengerId,Survived\n3,0\n",
        }
        downloaded: list[DownloadedFile] = []
        for name, content in files.items():
            path = output_dir / name
            path.write_text(content, encoding="utf-8")
            downloaded.append(DownloadedFile(path=path, size=path.stat().st_size))
        return downloaded


def test_kgx_bootstrap_status_and_replay_create_resumable_runtime_state(
    monkeypatch,
) -> None:
    tmp_path = _workspace("bootstrap")
    monkeypatch.setattr(kgx_main, "KaggleAccessAdapter", FakeKaggleAdapter)
    runner = CliRunner()

    bootstrap = runner.invoke(
        kgx_main.app,
        ["bootstrap", "titanic", "--repo", str(tmp_path)],
    )

    assert bootstrap.exit_code == 0
    assert "Bootstrapped KGMON mission: titanic" in bootstrap.stdout

    active_competition = _read_json(
        tmp_path / ".kgmon" / "state" / "active-competition.json"
    )
    assert active_competition["slug"] == "titanic"
    assert active_competition["workspace"] == "competitions/titanic"

    mission = _read_json(tmp_path / ".kgmon" / "state" / "missions" / "titanic.json")
    assert mission["name"] == "titanic"
    assert mission["competition_slug"] == "titanic"
    assert mission["status"] == "bootstrapped"
    assert mission["artifact_descriptor_path"] == "missions/titanic/artifacts.json"

    descriptors = _read_json(
        tmp_path / ".kgmon" / "missions" / "titanic" / "artifacts.json"
    )
    assert [descriptor["type"] for descriptor in descriptors["artifacts"]] == [
        "raw_data",
        "raw_data",
        "raw_data",
    ]
    assert "PassengerId" not in json.dumps(descriptors)

    status = runner.invoke(kgx_main.app, ["status", "--repo", str(tmp_path)])
    assert status.exit_code == 0
    assert "competition: titanic" in status.stdout
    assert "mission: titanic" in status.stdout
    assert "artifacts: 3" in status.stdout

    replay = runner.invoke(kgx_main.app, ["replay", "latest", "--repo", str(tmp_path)])
    assert replay.exit_code == 0
    assert "kgx bootstrap titanic" in replay.stdout
    assert "DATA_DOWNLOADED" in replay.stdout
    assert "PassengerId" not in replay.stdout


def test_event_bus_and_hook_runner_write_structured_redacted_logs() -> None:
    tmp_path = _workspace("hooks")
    RuntimeSetup(tmp_path).setup_local()
    bus = EventBus(tmp_path / ".kgmon")
    session_id = bus.start_session(command="kgx test-hooks")

    hooks = [
        HookDefinition(
            name="b-second",
            event=EventType.AFTER_COMMAND,
            command=f"{sys.executable} -c \"print('KAGGLE_KEY=secret-value')\"",
        ),
        HookDefinition(
            name="a-first",
            event=EventType.AFTER_COMMAND,
            command=f"{sys.executable} -c \"print('ok')\"",
        ),
    ]

    results = HookRunner(tmp_path / ".kgmon", hooks=hooks).run(
        EventType.AFTER_COMMAND,
        session_id=session_id,
    )

    assert [result.name for result in results] == ["a-first", "b-second"]
    assert all(result.status == "passed" for result in results)

    events = _read_jsonl(tmp_path / ".kgmon" / "logs" / "events.jsonl")
    assert events[0]["event_type"] == "SESSION_START"
    assert events[0]["session_id"] == session_id

    hook_logs = _read_jsonl(tmp_path / ".kgmon" / "logs" / "hooks.jsonl")
    assert [entry["hook"] for entry in hook_logs] == ["a-first", "b-second"]
    assert "secret-value" not in json.dumps(hook_logs)
    assert "KAGGLE_KEY=***" in json.dumps(hook_logs)


def _workspace(name: str) -> Path:
    path = Path("test-output") / "m7-runtime" / f"{name}-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    return path


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
