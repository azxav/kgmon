from __future__ import annotations

from typing import Any

RUNTIME_CONFIG_FILENAME = "runtime-config.json"


def default_runtime_config() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "runtime": {
            "name": "kgmon-codex",
            "launcher": "kgx",
            "state_root": ".kgmon",
        },
        "mcp": {
            "server": "kgmon",
            "command": "python",
            "args": ["-m", "kgmon_mcp.stdio"],
        },
        "security": {
            "default_mode": "standard",
            "strict_env_var": "KGMON_SECURITY",
            "auto_submit": "disabled",
        },
    }


def default_hud_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "active_mode": None,
        "active_competition": None,
        "active_mission": None,
        "security": {"mode": "standard"},
    }


def default_project_memory() -> dict[str, Any]:
    return {"schema_version": 1, "entries": []}


def default_security_policy() -> str:
    return "\n".join(
        (
            "schema_version: 1",
            "mode: standard",
            "strict_env_var: KGMON_SECURITY",
            "auto_submit: disabled",
            "remote_mcp:",
            "  approved:",
            "    - kgmon",
            "kaggle:",
            "  require_rule_audit: true",
            "  require_submission_confirmation: true",
            "",
        )
    )
