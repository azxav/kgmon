from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kgmon_runtime.redaction import redact_value

STRICT_ENV_VAR = "KGMON_SECURITY"


class SecurityViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class SecurityPolicy:
    repo: Path
    mode: str

    @classmethod
    def for_repo(cls, repo: Path) -> SecurityPolicy:
        requested = os.environ.get(STRICT_ENV_VAR, "").strip().lower()
        mode = "strict" if requested == "strict" else "standard"
        return cls(repo=repo.resolve(), mode=mode)

    def is_strict(self) -> bool:
        return self.mode == "strict"

    def allowed_roots(self) -> tuple[Path, ...]:
        return (
            self.repo / ".kgmon",
            self.repo / "competitions",
        )

    def require_path_allowed(self, path: Path) -> None:
        if not self.is_strict():
            return
        resolved = path.resolve()
        if any(_is_relative_to(resolved, root) for root in self.allowed_roots()):
            return
        self.log(
            "path_denied",
            {
                "path": str(resolved),
                "allowed_roots": [str(root) for root in self.allowed_roots()],
            },
        )
        raise SecurityViolation(f"path is not allowed in strict mode: {path}")

    def log(self, event: str, payload: dict[str, Any] | None = None) -> None:
        log_path = self.repo / ".kgmon" / "logs" / "security.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "schema_version": 1,
            "timestamp": _utc_now(),
            "event": event,
            "mode": self.mode,
            "payload": redact_value(payload or {}),
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    def doctor_messages(self) -> list[str]:
        if not self.is_strict():
            return []
        self.log(
            "strict_doctor_checked",
            {
                "auto_submit": "disabled",
                "external_data": "requires_rules_approval",
            },
        )
        return [
            "strict security mode is healthy",
            "auto-submit disabled without explicit confirmation",
            "external data requires rules approval",
        ]


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
