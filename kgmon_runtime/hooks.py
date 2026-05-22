from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kgmon_runtime.events import EventType
from kgmon_runtime.redaction import SECRET_NAMES, redact_text


@dataclass(frozen=True)
class HookDefinition:
    name: str
    event: EventType
    command: str
    enabled: bool = True
    timeout_seconds: int = 60
    severity: str = "blocking"
    network: bool = False
    write_paths: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HookResult:
    name: str
    event: EventType
    status: str
    exit_code: int | None
    severity: str
    duration_ms: int


class HookRunner:
    def __init__(
        self,
        state_root: Path,
        *,
        hooks: list[HookDefinition] | None = None,
    ) -> None:
        self.state_root = state_root
        self.hooks = hooks if hooks is not None else self._load_hooks()
        self.log_path = state_root / "logs" / "hooks.jsonl"

    def run(
        self,
        event: EventType,
        *,
        session_id: str | None = None,
    ) -> list[HookResult]:
        selected = sorted(
            (hook for hook in self.hooks if hook.enabled and hook.event == event),
            key=lambda hook: hook.name,
        )
        return [self._run_one(hook, session_id=session_id) for hook in selected]

    def _run_one(
        self,
        hook: HookDefinition,
        *,
        session_id: str | None,
    ) -> HookResult:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                hook.command,
                cwd=self.state_root.parent,
                env=_redacted_env(),
                shell=True,
                capture_output=True,
                text=True,
                timeout=hook.timeout_seconds,
                check=False,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            status = "passed" if completed.returncode == 0 else "failed"
            result = HookResult(
                name=hook.name,
                event=hook.event,
                status=status,
                exit_code=completed.returncode,
                severity=hook.severity,
                duration_ms=duration_ms,
            )
            self._log_result(
                hook,
                result,
                session_id=session_id,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
            return result
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            result = HookResult(
                name=hook.name,
                event=hook.event,
                status="timeout",
                exit_code=None,
                severity=hook.severity,
                duration_ms=duration_ms,
            )
            self._log_result(
                hook,
                result,
                session_id=session_id,
                stdout=_output_to_text(exc.stdout),
                stderr=_output_to_text(exc.stderr),
            )
            return result

    def _log_result(
        self,
        hook: HookDefinition,
        result: HookResult,
        *,
        session_id: str | None,
        stdout: str,
        stderr: str,
    ) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        entry: dict[str, Any] = {
            "schema_version": 1,
            "session_id": session_id,
            "hook": hook.name,
            "event_type": hook.event.value,
            "status": result.status,
            "exit_code": result.exit_code,
            "severity": hook.severity,
            "duration_ms": result.duration_ms,
            "security": {
                "network": hook.network,
                "write_paths": list(hook.write_paths),
            },
            "stdout": redact_text(stdout),
            "stderr": redact_text(stderr),
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    def _load_hooks(self) -> list[HookDefinition]:
        hooks_dir = self.state_root / "hooks"
        if not hooks_dir.exists():
            return []
        hooks: list[HookDefinition] = []
        for path in sorted(hooks_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            hooks.append(
                HookDefinition(
                    name=str(payload["name"]),
                    event=EventType(str(payload["event"])),
                    command=str(payload["command"]),
                    enabled=bool(payload.get("enabled", True)),
                    timeout_seconds=int(payload.get("timeout_seconds", 60)),
                    severity=str(payload.get("severity", "blocking")),
                    network=bool(payload.get("security", {}).get("network", False)),
                    write_paths=tuple(
                        str(item)
                        for item in payload.get("security", {}).get("write_paths", [])
                    ),
                )
            )
        return hooks


def _redacted_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in SECRET_NAMES}


def _output_to_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
