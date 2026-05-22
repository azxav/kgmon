from __future__ import annotations

SECRET_KEYS = frozenset(
    {
        "KAGGLE_USERNAME",
        "KAGGLE_KEY",
        "KAGGLE_API_TOKEN",
        "OPENAI_API_KEY",
        "WANDB_API_KEY",
        "HF_TOKEN",
    }
)


def redact_secret(value: str | None) -> str:
    if not value:
        return "<missing>"
    if len(value) <= 2:
        return "*" * len(value)
    if len(value) == 3:
        return f"{value[:1]}**{value[-1:]}"

    visible_prefix = value[:2]
    visible_suffix = value[-2:]
    hidden_count = min(max(len(value) - 4, 2), 20)
    return f"{visible_prefix}{'*' * hidden_count}{visible_suffix}"


def redact_mapping(values: dict[str, str | None]) -> dict[str, str]:
    return {key: redact_secret(value) for key, value in values.items()}
