from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kgmon_core.registry import ArtifactRegistry


@dataclass(frozen=True)
class ArtifactDescriptor:
    type: str
    path: str
    hash: str
    run_id: str | None = None
    uri: str | None = None
    metadata: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "path": self.path,
            "hash": self.hash,
            "run_id": self.run_id,
            "uri": self.uri,
            "metadata": self.metadata or {},
        }


def descriptors_from_registry(workspace: Path) -> list[ArtifactDescriptor]:
    descriptors: list[ArtifactDescriptor] = []
    for artifact in ArtifactRegistry(workspace).list_artifacts():
        descriptors.append(
            ArtifactDescriptor(
                run_id=artifact.run_id,
                type=artifact.type,
                path=artifact.path,
                hash=artifact.hash,
                uri=f"kgmon://competition/current/artifacts/{artifact.path}",
            )
        )
    return descriptors


def write_artifact_descriptors(
    state_root: Path,
    *,
    mission_name: str,
    descriptors: list[ArtifactDescriptor],
) -> Path:
    path = state_root / "missions" / mission_name / "artifacts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "mission": mission_name,
        "artifacts": [descriptor.to_json() for descriptor in descriptors],
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
