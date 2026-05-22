from __future__ import annotations

from typing import Any

from kgmon_mcp.server import run_public_tool


def run_workflow_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return run_public_tool(name, arguments)
