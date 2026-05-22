from __future__ import annotations

from typing import Any

from kgmon_mcp.server import list_mcp_resources, read_mcp_resource

__all__ = ["list_mcp_resources", "read_mcp_resource"]


def list_resources() -> list[dict[str, Any]]:
    return list_mcp_resources()


def read_resource(uri: str, *, workspace_root: str | None = None) -> dict[str, Any]:
    return read_mcp_resource(uri, workspace_root=workspace_root)
