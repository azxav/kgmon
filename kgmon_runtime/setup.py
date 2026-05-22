from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kgmon_runtime.config import (
    RUNTIME_CONFIG_FILENAME,
    default_hud_state,
    default_project_memory,
    default_runtime_config,
    default_security_policy,
)
from kgmon_runtime.dsml import install_dsml_pack
from kgmon_runtime.mcp_config import repair_mcp_config

STATE_DIRECTORIES = (
    "state/sessions",
    "state/missions",
    "state/team",
    "state/interop",
    "state/locks",
    "missions",
    "research",
    "runs",
    "hud",
    "hooks",
    "logs",
    "skills/dsml",
    "prompts/dsml",
    "agent-contracts/dsml",
    "checklists/dsml",
)

LOG_NAMES = ("events", "hooks", "security", "verification", "mcp")


@dataclass(frozen=True)
class RuntimeSetupResult:
    state_root: Path
    config_path: Path
    mcp_path: Path


class RuntimeSetup:
    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.state_root = repo / ".kgmon"

    def setup_local(self, *, repair: bool = False) -> RuntimeSetupResult:
        for relative in STATE_DIRECTORIES:
            (self.state_root / relative).mkdir(parents=True, exist_ok=True)

        self._write_json(
            self.state_root / RUNTIME_CONFIG_FILENAME,
            default_runtime_config(),
            repair=repair,
        )
        self._write_json(
            self.state_root / "project-memory.json",
            default_project_memory(),
            repair=repair,
        )
        self._write_text(
            self.state_root / "notepad.md",
            "# KGMON Notepad\n",
            repair=repair,
        )
        self._write_json(
            self.state_root / "hud" / "current.json",
            default_hud_state(),
            repair=repair,
        )
        self._write_text(
            self.state_root / "security-policy.yaml",
            default_security_policy(),
            repair=repair,
        )
        for name in LOG_NAMES:
            self._write_text(
                self.state_root / "logs" / f"{name}.jsonl",
                "",
                repair=False,
            )
        install_dsml_pack(self.state_root, repair=repair)

        mcp_path = repair_mcp_config(self.repo)
        return RuntimeSetupResult(
            state_root=self.state_root,
            config_path=self.state_root / RUNTIME_CONFIG_FILENAME,
            mcp_path=mcp_path,
        )

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any], *, repair: bool) -> None:
        if path.exists() and not repair:
            return
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _write_text(path: Path, text: str, *, repair: bool) -> None:
        if path.exists() and not repair:
            return
        path.write_text(text, encoding="utf-8")
