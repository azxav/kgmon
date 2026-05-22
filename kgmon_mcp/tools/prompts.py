from __future__ import annotations

from typing import Any

from kgmon_mcp.server import run_public_tool


def kgmon_prompts_list(arguments: dict[str, Any]) -> dict[str, Any]:
    return run_public_tool("kgmon_prompts_list", arguments)


def kgmon_prompt_run(arguments: dict[str, Any]) -> dict[str, Any]:
    return run_public_tool("kgmon_prompt_run", arguments)
