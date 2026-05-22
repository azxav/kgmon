from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kgmon_core.config import update_competition_config


@dataclass(frozen=True)
class ParsedRules:
    metric_name: str
    metric_direction: str
    external_data: str
    internet_allowed: bool | None
    human_review_required: bool


class RuleMetricParser:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def parse_and_update_config(self) -> ParsedRules:
        content = _read_kaggle_pages(self.workspace)
        parsed = ParsedRules(
            metric_name=_detect_metric(content),
            metric_direction=_metric_direction(_detect_metric(content)),
            external_data=_detect_external_data_rule(content),
            internet_allowed=_detect_internet_rule(content),
            human_review_required=False,
        )

        parsed = ParsedRules(
            metric_name=parsed.metric_name,
            metric_direction=parsed.metric_direction,
            external_data=parsed.external_data,
            internet_allowed=parsed.internet_allowed,
            human_review_required=(
                parsed.metric_name == "pending"
                or parsed.external_data == "unknown"
                or parsed.internet_allowed is None
            ),
        )
        update_competition_config(
            self.workspace,
            {
                "competition.metric.name": parsed.metric_name,
                "competition.metric.direction": parsed.metric_direction,
                "rules.external_data": parsed.external_data,
                "rules.internet_allowed": _bool_or_unknown(parsed.internet_allowed),
                "rules.human_review_required": str(
                    parsed.human_review_required
                ).lower(),
            },
        )
        return parsed


def _read_kaggle_pages(workspace: Path) -> str:
    pages_dir = workspace / "kaggle" / "pages"
    if not pages_dir.exists():
        return ""
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace").lower()
        for path in sorted(pages_dir.glob("*.md"))
    )


def _detect_metric(content: str) -> str:
    checks = (
        ("roc_auc", ("roc_auc", "roc auc", "area under the roc")),
        ("auc", ("auc", "area under curve")),
        ("log_loss", ("log loss", "logloss")),
        ("rmse", ("rmse", "root mean squared error")),
        ("rmsle", ("rmsle", "root mean squared logarithmic error")),
        ("mae", ("mae", "mean absolute error")),
        ("accuracy", ("accuracy", "accurate")),
        ("f1", ("f1", "f1 score")),
    )
    for metric, needles in checks:
        if any(needle in content for needle in needles):
            return metric
    return "pending"


def _metric_direction(metric: str) -> str:
    if metric in {"log_loss", "rmse", "rmsle", "mae"}:
        return "minimize"
    return "maximize"


def _detect_external_data_rule(content: str) -> str:
    forbidden = (
        "no external data",
        "external data is not allowed",
        "may not use external data",
        "must not use external data",
        "cannot use external data",
    )
    allowed = (
        "external data is allowed",
        "may use external data",
        "can use external data",
    )
    if any(phrase in content for phrase in forbidden):
        return "forbidden"
    if any(phrase in content for phrase in allowed):
        return "allowed"
    return "unknown"


def _detect_internet_rule(content: str) -> bool | None:
    disabled = (
        "internet access is disabled",
        "internet is disabled",
        "no internet",
        "internet access is not allowed",
    )
    enabled = (
        "internet access is enabled",
        "internet is enabled",
        "internet access is allowed",
    )
    if any(phrase in content for phrase in disabled):
        return False
    if any(phrase in content for phrase in enabled):
        return True
    return None


def _bool_or_unknown(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "true" if value else "false"
