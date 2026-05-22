from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def read_competition_config(workspace: Path) -> dict[str, Any]:
    path = workspace / "configs" / "competition.yaml"
    values: dict[str, Any] = {}
    section: str | None = None
    subsection: str | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1]
            subsection = None
            continue
        if section is None or ":" not in stripped:
            continue

        key, raw_value = stripped.split(":", 1)
        value = _parse_scalar(raw_value.strip())
        if indent == 2 and raw_value.strip() == "":
            subsection = key
            continue
        if indent == 2:
            values[f"{section}.{key}"] = value
            subsection = None
        elif indent == 4 and subsection is not None:
            values[f"{section}.{subsection}.{key}"] = value

    return values


def update_competition_config(workspace: Path, replacements: dict[str, str]) -> None:
    path = workspace / "configs" / "competition.yaml"
    text = path.read_text(encoding="utf-8")

    for dotted_key, value in replacements.items():
        if dotted_key == "competition.task_family":
            text = _replace_line(text, "  task_family", value)
        elif dotted_key == "competition.target_column":
            text = _replace_line(text, "  target_column", value)
        elif dotted_key == "competition.id_column":
            text = _replace_line(text, "  id_column", value)
        elif dotted_key == "competition.metric.name":
            text = _replace_nested_line(text, "  metric:", "    name", value)
        elif dotted_key == "competition.metric.direction":
            text = _replace_nested_line(text, "  metric:", "    direction", value)
        elif dotted_key == "competition.submission.id_column":
            text = _replace_nested_line(text, "  submission:", "    id_column", value)
        elif dotted_key == "competition.submission.prediction_columns":
            text = _replace_nested_line(
                text,
                "  submission:",
                "    prediction_columns",
                value,
            )
        elif dotted_key == "rules.external_data":
            text = _replace_line(text, "  external_data", value)
        elif dotted_key == "rules.internet_allowed":
            text = _replace_line(text, "  internet_allowed", value)
        elif dotted_key == "rules.human_review_required":
            text = _replace_line(text, "  human_review_required", value)
        elif dotted_key == "validation.strategy":
            text = _replace_line(text, "  strategy", value)

    path.write_text(text, encoding="utf-8")


def yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _parse_scalar(value: str) -> Any:
    if value == "null":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [item.strip() for item in inner.split(",")]
    try:
        return int(value)
    except ValueError:
        return value


def _replace_line(text: str, key_prefix: str, value: str) -> str:
    pattern = re.compile(rf"(?m)^{re.escape(key_prefix)}: .*$")
    replacement = f"{key_prefix}: {value}"
    return pattern.sub(replacement, text, count=1)


def _replace_nested_line(
    text: str,
    parent_line: str,
    key_prefix: str,
    value: str,
) -> str:
    parent_index = text.find(parent_line)
    if parent_index == -1:
        return text

    before = text[:parent_index]
    after = text[parent_index:]
    pattern = re.compile(rf"(?m)^{re.escape(key_prefix)}: .*$")
    return before + pattern.sub(f"{key_prefix}: {value}", after, count=1)
