from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KGX_MCP_SERVER: dict[str, Any] = {
    "command": "python",
    "args": ["-m", "kgmon_mcp.stdio"],
    "env": {"KGMON_HOME": ".", "KGMON_SECURITY": "strict"},
    "x-kgmon-managed": True,
}

SUPPORTED_MCP_CLIENTS = ("codex", "claude", "cursor", "vscode")


def repair_mcp_config(repo: Path) -> Path:
    path = repo / ".mcp.json"
    payload = _read_mcp_payload(path)
    servers = payload.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        payload["mcpServers"] = servers

    servers["kgmon"] = client_server_config(repo, "codex")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def client_server_config(repo: Path, client: str) -> dict[str, Any]:
    if client not in SUPPORTED_MCP_CLIENTS:
        raise ValueError(f"unsupported MCP client: {client}")
    payload = dict(KGX_MCP_SERVER)
    payload["env"] = {
        "KGMON_HOME": str(repo.resolve()),
        "KGMON_SECURITY": "strict",
    }
    return payload


def client_config_template(repo: Path, client: str) -> dict[str, Any]:
    server = client_server_config(repo, client)
    if client == "vscode":
        return {"servers": {"kgmon": {"type": "stdio", **server}}}
    return {"mcpServers": {"kgmon": server}}


def install_client_config(repo: Path, client: str) -> Path:
    payload = client_config_template(repo, client)
    path = repo / ".mcp.json"
    if client == "vscode":
        vscode_dir = repo / ".vscode"
        vscode_dir.mkdir(parents=True, exist_ok=True)
        path = vscode_dir / "mcp.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def doctor_client_config(repo: Path, client: str) -> list[str]:
    path = repo / ".mcp.json"
    if client == "vscode":
        path = repo / ".vscode" / "mcp.json"
    if not path.exists():
        return [f"missing {path}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [f"invalid JSON in {path}"]
    expected = client_config_template(repo, client)
    return [] if payload == expected else [f"{client} MCP config differs from template"]


def is_managed_kgmon_server(value: object) -> bool:
    return value == KGX_MCP_SERVER


def _read_mcp_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"mcpServers": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"mcpServers": {}}
    if not isinstance(payload, dict):
        return {"mcpServers": {}}
    return payload
