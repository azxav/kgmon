from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from kgmon_runtime.redaction import redact_value


class EventType(StrEnum):
    SESSION_START = "SESSION_START"
    SESSION_END = "SESSION_END"
    USER_PROMPT_SUBMIT = "USER_PROMPT_SUBMIT"
    BEFORE_TOOL_CALL = "BEFORE_TOOL_CALL"
    AFTER_TOOL_CALL = "AFTER_TOOL_CALL"
    BEFORE_COMMAND = "BEFORE_COMMAND"
    AFTER_COMMAND = "AFTER_COMMAND"
    FILE_CREATED = "FILE_CREATED"
    FILE_MODIFIED = "FILE_MODIFIED"
    DATA_DOWNLOADED = "DATA_DOWNLOADED"
    PROFILE_CREATED = "PROFILE_CREATED"
    VALIDATION_FIXED = "VALIDATION_FIXED"
    EXPERIMENT_STARTED = "EXPERIMENT_STARTED"
    EXPERIMENT_COMPLETED = "EXPERIMENT_COMPLETED"
    EXPERIMENT_FAILED = "EXPERIMENT_FAILED"
    ENSEMBLE_CREATED = "ENSEMBLE_CREATED"
    PACKAGE_CREATED = "PACKAGE_CREATED"
    VERIFY_STARTED = "VERIFY_STARTED"
    VERIFY_COMPLETED = "VERIFY_COMPLETED"
    SUBMISSION_REQUESTED = "SUBMISSION_REQUESTED"
    SUBMISSION_COMPLETED = "SUBMISSION_COMPLETED"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"


class EventBus:
    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root
        self.log_path = state_root / "logs" / "events.jsonl"
        self.sessions_dir = state_root / "state" / "sessions"

    def start_session(self, *, command: str) -> str:
        session_id = uuid.uuid4().hex
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        session_payload = {
            "schema_version": 1,
            "session_id": session_id,
            "command": command,
            "started_at": _utc_now(),
        }
        _write_json(session_dir / "session.json", session_payload)
        self.emit(
            EventType.SESSION_START,
            session_id=session_id,
            payload={"command": command},
        )
        return session_id

    def emit(
        self,
        event_type: EventType,
        *,
        session_id: str | None = None,
        mission: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "schema_version": 1,
            "timestamp": _utc_now(),
            "event_type": event_type.value,
            "session_id": session_id,
            "mission": mission,
            "payload": redact_value(payload or {}),
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        return event

    def list_events(self, *, session_id: str | None = None) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if session_id is None or event.get("session_id") == session_id:
                events.append(event)
        return events

    def latest_session_id(self) -> str | None:
        for event in reversed(self.list_events()):
            session_id = event.get("session_id")
            if isinstance(session_id, str) and session_id:
                return session_id
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
