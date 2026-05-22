from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kgmon_agents.registry import AgentRole

MAX_SUMMARY_CHARS = 4096
MAX_METADATA_BYTES = 8192


class HandoffLimitError(ValueError):
    """Raised when a worker tries to hand off unbounded or final artifacts."""


@dataclass(frozen=True)
class WorkerHandoff:
    role: AgentRole
    mission: str
    artifact_type: str
    artifact_path: str
    summary: str
    metadata: dict[str, Any]

    @classmethod
    def create(
        cls,
        *,
        role: AgentRole,
        mission: str,
        artifact_type: str,
        artifact_path: Path,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> WorkerHandoff:
        if len(summary) > MAX_SUMMARY_CHARS:
            raise HandoffLimitError("handoff summary exceeds 4096 characters")
        path_text = artifact_path.as_posix()
        if _is_shared_final_artifact(path_text):
            raise HandoffLimitError("workers must not write shared final artifacts")
        metadata_payload = metadata or {}
        metadata_size = len(json.dumps(metadata_payload, sort_keys=True).encode())
        if metadata_size > MAX_METADATA_BYTES:
            raise HandoffLimitError("handoff metadata exceeds 8192 bytes")
        return cls(
            role=role,
            mission=mission,
            artifact_type=artifact_type,
            artifact_path=path_text,
            summary=summary,
            metadata=metadata_payload,
        )

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "role": self.role.id,
            "mission": self.mission,
            "artifact": {
                "type": self.artifact_type,
                "path": self.artifact_path,
                "uri": f"kgmon://competition/current/artifacts/{self.artifact_path}",
                "metadata": self.metadata,
            },
            "summary": self.summary,
        }


def _is_shared_final_artifact(path_text: str) -> bool:
    parts = path_text.split("/")
    return any(
        left == "artifacts" and right == "final"
        for left, right in zip(parts, parts[1:], strict=False)
    )
