from __future__ import annotations

import re
from typing import Any

SECRET_NAMES = (
    "KAGGLE_USERNAME",
    "KAGGLE_KEY",
    "KAGGLE_API_TOKEN",
    "OPENAI_API_KEY",
    "WANDB_API_KEY",
    "HF_TOKEN",
)


def redact_text(text: str) -> str:
    redacted = text
    for name in SECRET_NAMES:
        redacted = re.sub(rf"({name}\s*[:=]\s*)[^\s\n'\"]+", r"\1***", redacted)
    return redacted


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): redact_value(item) for key, item in value.items()}
    return value
