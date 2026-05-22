from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from kgmon_runtime.config import RUNTIME_CONFIG_FILENAME, default_runtime_config
from kgmon_runtime.mcp_config import client_server_config
from kgmon_runtime.security import SecurityPolicy


@dataclass(frozen=True)
class RuntimeDoctorReport:
    ok: bool
    messages: list[str]


class RuntimeDoctor:
    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.state_root = repo / ".kgmon"

    def check(self) -> RuntimeDoctorReport:
        messages: list[str] = []
        if not self.state_root.is_dir():
            messages.append("missing .kgmon runtime state root")
        self._check_runtime_config(messages)
        self._check_mcp_config(messages)

        if messages:
            return RuntimeDoctorReport(ok=False, messages=messages)
        return RuntimeDoctorReport(
            ok=True,
            messages=[
                "kgx runtime skeleton is healthy",
                *SecurityPolicy.for_repo(self.repo).doctor_messages(),
            ],
        )

    def check_conflicts(self) -> RuntimeDoctorReport:
        messages: list[str] = []
        payload = self._read_json(self.repo / ".mcp.json")
        servers = payload.get("mcpServers") if isinstance(payload, dict) else None
        if not isinstance(servers, dict):
            messages.append(".mcp.json mcpServers must be an object")
        else:
            kgmon_server = servers.get("kgmon")
            if kgmon_server is not None and kgmon_server != client_server_config(
                self.repo, "codex"
            ):
                messages.append("kgmon MCP server is not managed by kgx setup")

        if messages:
            return RuntimeDoctorReport(ok=False, messages=messages)
        return RuntimeDoctorReport(
            ok=True,
            messages=["no kgx runtime conflicts detected"],
        )

    def _check_runtime_config(self, messages: list[str]) -> None:
        config_path = self.state_root / RUNTIME_CONFIG_FILENAME
        if not config_path.exists():
            messages.append("missing .kgmon/runtime-config.json")
            return
        payload = self._read_json(config_path)
        if payload != default_runtime_config():
            messages.append("invalid .kgmon/runtime-config.json schema")

    def _check_mcp_config(self, messages: list[str]) -> None:
        mcp_path = self.repo / ".mcp.json"
        if not mcp_path.exists():
            messages.append("missing .mcp.json")
            return
        payload = self._read_json(mcp_path)
        servers = payload.get("mcpServers") if isinstance(payload, dict) else None
        if not isinstance(servers, dict) or servers.get(
            "kgmon"
        ) != client_server_config(self.repo, "codex"):
            messages.append("missing managed kgmon MCP server")

    @staticmethod
    def _read_json(path: Path) -> object:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
