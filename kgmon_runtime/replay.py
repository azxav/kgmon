from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kgmon_runtime.events import EventBus


@dataclass(frozen=True)
class ReplaySummary:
    session_id: str | None
    command: str | None
    event_types: list[str]
    event_count: int


class SessionReplay:
    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root
        self.bus = EventBus(state_root)

    def summarize(self, session: str) -> ReplaySummary:
        session_id = self.bus.latest_session_id() if session == "latest" else session
        if session_id is None:
            return ReplaySummary(
                session_id=None,
                command=None,
                event_types=[],
                event_count=0,
            )
        events = self.bus.list_events(session_id=session_id)
        command = None
        for event in events:
            payload = event.get("payload")
            if isinstance(payload, dict) and isinstance(payload.get("command"), str):
                command = payload["command"]
                break
        return ReplaySummary(
            session_id=session_id,
            command=command,
            event_types=[str(event["event_type"]) for event in events],
            event_count=len(events),
        )
