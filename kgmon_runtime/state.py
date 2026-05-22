from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from kgmon_runtime.artifacts import ArtifactDescriptor, write_artifact_descriptors


@dataclass(frozen=True)
class MissionRecord:
    name: str
    competition_slug: str
    status: str
    workspace: str
    artifact_descriptor_path: str
    artifact_count: int
    session_id: str

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "name": self.name,
            "competition_slug": self.competition_slug,
            "status": self.status,
            "workspace": self.workspace,
            "artifact_descriptor_path": self.artifact_descriptor_path,
            "artifact_count": self.artifact_count,
            "session_id": self.session_id,
        }


class RuntimeState:
    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.state_root = repo / ".kgmon"

    def record_bootstrap(
        self,
        *,
        mission_name: str,
        competition_slug: str,
        workspace: Path,
        session_id: str,
        artifacts: list[ArtifactDescriptor],
    ) -> MissionRecord:
        descriptor_path = write_artifact_descriptors(
            self.state_root,
            mission_name=mission_name,
            descriptors=artifacts,
        )
        descriptor_relative = descriptor_path.relative_to(self.state_root).as_posix()
        workspace_relative = workspace.relative_to(self.repo).as_posix()
        record = MissionRecord(
            name=mission_name,
            competition_slug=competition_slug,
            status="bootstrapped",
            workspace=workspace_relative,
            artifact_descriptor_path=descriptor_relative,
            artifact_count=len(artifacts),
            session_id=session_id,
        )
        self._write_json(
            self.state_root / "state" / "missions" / f"{mission_name}.json",
            record.to_json(),
        )
        self._write_json(
            self.state_root / "state" / "active-competition.json",
            {
                "schema_version": 1,
                "slug": competition_slug,
                "workspace": workspace_relative,
                "mission": mission_name,
            },
        )
        self._write_json(
            self.state_root / "state" / "active-mode.json",
            {
                "schema_version": 1,
                "mode": "bootstrap",
                "mission": mission_name,
            },
        )
        self._write_json(
            self.state_root / "hud" / "current.json",
            {
                "schema_version": 1,
                "active_mode": "bootstrap",
                "active_competition": competition_slug,
                "active_mission": mission_name,
                "security": {"mode": "standard"},
                "artifacts": {
                    "count": len(artifacts),
                    "descriptor_path": descriptor_relative,
                },
            },
        )
        return record

    def current_status(self) -> dict[str, Any]:
        active = _read_json(self.state_root / "state" / "active-competition.json")
        mission_name = active.get("mission")
        mission: dict[str, Any] = {}
        if isinstance(mission_name, str):
            mission = _read_json(
                self.state_root / "state" / "missions" / f"{mission_name}.json"
            )
        active_mode = _read_json(self.state_root / "state" / "active-mode.json")
        return {
            "state_root": ".kgmon" if self.state_root.exists() else "missing",
            "competition": active.get("slug"),
            "mission": mission.get("name"),
            "mode": active_mode.get("mode"),
            "artifacts": mission.get("artifact_count", 0),
            "session_id": mission.get("session_id"),
        }

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
