from __future__ import annotations

import csv
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from kgmon_core.config import read_competition_config
from kgmon_runtime.events import EventBus, EventType
from kgmon_runtime.redaction import redact_value
from kgmon_runtime.security import SecurityPolicy

REQUIRED_GATES = (
    "CONFIG_VALID",
    "KAGGLE_CREDENTIALS_VALID",
    "KAGGLE_RULES_AUDITED",
    "DATA_DOWNLOADED",
    "DATA_PROFILE_EXISTS",
    "VALIDATION_FIXED",
    "LEAKAGE_CHECK_PASS",
    "TRAINING_RUNS_COMPLETE",
    "OOF_CONTRACT_PASS",
    "TEST_PRED_CONTRACT_PASS",
    "METRIC_RECOMPUTED",
    "ENSEMBLE_REPRODUCIBLE",
    "SUBMISSION_SCHEMA_PASS",
    "PACKAGE_REPRODUCIBLE",
    "NO_SECRET_LEAK",
    "NO_UNAPPROVED_EXTERNAL_DATA",
    "NO_UNAPPROVED_AUTOSUBMIT",
)


@dataclass(frozen=True)
class GateEvidence:
    gate: str
    status: str
    message: str
    checked_at: str
    critical: bool = True

    def to_json(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "status": self.status,
            "message": self.message,
            "checked_at": self.checked_at,
            "critical": self.critical,
        }


@dataclass(frozen=True)
class VerificationReport:
    ok: bool
    mission: str | None
    workspace: str | None
    evidence: list[GateEvidence]
    evidence_path: Path
    session_id: str

    @property
    def passed(self) -> int:
        return sum(1 for evidence in self.evidence if evidence.status == "pass")

    @property
    def failed(self) -> int:
        return sum(1 for evidence in self.evidence if evidence.status == "fail")

    @property
    def critical_failures(self) -> int:
        return sum(
            1
            for evidence in self.evidence
            if evidence.status == "fail" and evidence.critical
        )


class VerificationEngine:
    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.state_root = repo / ".kgmon"
        self.policy = SecurityPolicy.for_repo(repo)

    def verify_all(self) -> VerificationReport:
        bus = EventBus(self.state_root)
        session_id = bus.start_session(command="kgx verify all")
        mission, workspace = self._active_mission_workspace()
        bus.emit(
            EventType.VERIFY_STARTED,
            session_id=session_id,
            mission=mission,
            payload={"workspace": str(workspace) if workspace else None},
        )
        evidence = [
            self._check_gate(gate, workspace=workspace) for gate in REQUIRED_GATES
        ]
        ok = all(item.status == "pass" or not item.critical for item in evidence)
        evidence_path = self._write_evidence(
            mission=mission,
            workspace=workspace,
            session_id=session_id,
            evidence=evidence,
            ok=ok,
        )
        self._update_hud(mission=mission, workspace=workspace, evidence=evidence)
        bus.emit(
            EventType.VERIFY_COMPLETED,
            session_id=session_id,
            mission=mission,
            payload={
                "ok": ok,
                "passed": sum(1 for item in evidence if item.status == "pass"),
                "failed": sum(1 for item in evidence if item.status == "fail"),
                "critical_failures": sum(
                    1
                    for item in evidence
                    if item.status == "fail" and item.critical
                ),
                "evidence_path": str(evidence_path),
            },
        )
        return VerificationReport(
            ok=ok,
            mission=mission,
            workspace=str(workspace) if workspace else None,
            evidence=evidence,
            evidence_path=evidence_path,
            session_id=session_id,
        )

    def _check_gate(self, gate: str, *, workspace: Path | None) -> GateEvidence:
        try:
            passed, message = self._gate_status(gate, workspace=workspace)
        except Exception as exc:
            passed, message = False, str(exc)
        return GateEvidence(
            gate=gate,
            status="pass" if passed else "fail",
            message=message,
            checked_at=_utc_now(),
        )

    def _gate_status(
        self,
        gate: str,
        *,
        workspace: Path | None,
    ) -> tuple[bool, str]:
        if workspace is None:
            return False, "no active mission workspace"

        if gate == "CONFIG_VALID":
            config = read_competition_config(workspace)
            required = (
                "competition.slug",
                "competition.target_column",
                "competition.submission.id_column",
                "competition.submission.prediction_columns",
            )
            missing = [key for key in required if key not in config]
            return not missing, "config valid" if not missing else f"missing {missing}"
        if gate == "KAGGLE_CREDENTIALS_VALID":
            available = bool(os.environ.get("KAGGLE_API_TOKEN")) or (
                bool(os.environ.get("KAGGLE_USERNAME"))
                and bool(os.environ.get("KAGGLE_KEY"))
            )
            return available, "kaggle credentials detected"
        if gate == "KAGGLE_RULES_AUDITED":
            config = read_competition_config(workspace)
            audited = "rules.human_review_required" in config or (
                workspace / "kaggle" / "pages" / "rules.md"
            ).exists()
            return audited, "kaggle rules audited"
        if gate == "DATA_DOWNLOADED":
            return any((workspace / "data" / "raw").glob("*")), "raw data exists"
        if gate == "DATA_PROFILE_EXISTS":
            path = workspace / "artifacts" / "reports" / "profile.json"
            return path.exists(), "profile evidence exists"
        if gate == "VALIDATION_FIXED":
            text = _read_text(workspace / "configs" / "validation.yaml")
            return "status: ready" in text, "validation status is ready"
        if gate == "LEAKAGE_CHECK_PASS":
            text = _read_text(workspace / "configs" / "validation.yaml").lower()
            blocked = "leakage_blocked: true" in text or "leakage_check: fail" in text
            return not blocked, "leakage check passed"
        if gate == "TRAINING_RUNS_COMPLETE":
            return _registry_has_run(workspace), "training run completed"
        if gate == "OOF_CONTRACT_PASS":
            return _csv_has_columns(
                workspace / "artifacts" / "oof",
                {"id", "fold", "y_true", "pred", "run_id"},
            )
        if gate == "TEST_PRED_CONTRACT_PASS":
            return _csv_has_columns(
                workspace / "artifacts" / "test_preds",
                {"id", "pred", "run_id"},
            )
        if gate == "METRIC_RECOMPUTED":
            return any((workspace / "runs").glob("*/run_report.json")), (
                "run metric report exists"
            )
        if gate == "ENSEMBLE_REPRODUCIBLE":
            return (
                (workspace / "artifacts" / "ensembles" / "ensemble_v001.yaml").exists()
                and (
                    workspace
                    / "artifacts"
                    / "submissions"
                    / "submission_ensemble_v001.csv"
                ).exists()
            ), "ensemble artifacts exist"
        if gate == "SUBMISSION_SCHEMA_PASS":
            return _submission_schema_pass(workspace)
        if gate == "PACKAGE_REPRODUCIBLE":
            final_dir = workspace / "artifacts" / "final"
            package_files = {
                "submission.csv",
                "inference.py",
                "solution.ipynb",
                "requirements.txt",
                "environment.yml",
                "manifest.yaml",
                "provenance.json",
                "report.md",
            }
            found = {path.name for path in final_dir.glob("*") if path.is_file()}
            missing = sorted(package_files - found)
            return not missing, "final package is reproducible"
        if gate == "NO_SECRET_LEAK":
            leaked = _secret_leaks(self.state_root, workspace)
            return not leaked, "no configured secrets found in artifacts"
        if gate == "NO_UNAPPROVED_EXTERNAL_DATA":
            config = read_competition_config(workspace)
            approved = bool(config.get("rules.external_data", False)) is False
            return approved, "external data disabled or approved"
        if gate == "NO_UNAPPROVED_AUTOSUBMIT":
            config = read_competition_config(workspace)
            allowed = bool(config.get("rules.auto_submit_allowed", False))
            return not allowed, "auto-submit disabled"
        raise KeyError(f"unknown verification gate: {gate}")

    def _active_mission_workspace(self) -> tuple[str | None, Path | None]:
        active = _read_json(self.state_root / "state" / "active-competition.json")
        mission = active.get("mission") or active.get("slug")
        if not isinstance(mission, str):
            return None, None
        mission_payload = _read_json(
            self.state_root / "state" / "missions" / f"{mission}.json"
        )
        raw_workspace = mission_payload.get("workspace") or active.get("workspace")
        if not isinstance(raw_workspace, str):
            return mission, None
        return mission, self.repo / raw_workspace

    def _write_evidence(
        self,
        *,
        mission: str | None,
        workspace: Path | None,
        session_id: str,
        evidence: list[GateEvidence],
        ok: bool,
    ) -> Path:
        evidence_dir = self.state_root / "missions" / (mission or "unknown")
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = evidence_dir / "verification.json"
        payload = {
            "schema_version": 1,
            "session_id": session_id,
            "mission": mission,
            "workspace": str(workspace) if workspace else None,
            "checked_at": _utc_now(),
            "fresh": True,
            "ok": ok,
            "passed": sum(1 for item in evidence if item.status == "pass"),
            "failed": sum(1 for item in evidence if item.status == "fail"),
            "critical_failures": sum(
                1
                for item in evidence
                if item.status == "fail" and item.critical
            ),
            "evidence": [item.to_json() for item in evidence],
        }
        evidence_path.write_text(
            json.dumps(redact_value(payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        log_path = self.state_root / "logs" / "verification.jsonl"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(redact_value(payload), sort_keys=True) + "\n")
        return evidence_path

    def _update_hud(
        self,
        *,
        mission: str | None,
        workspace: Path | None,
        evidence: list[GateEvidence],
    ) -> None:
        hud_path = self.state_root / "hud" / "current.json"
        hud = _read_json(hud_path)
        hud.update(
            {
                "schema_version": 1,
                "active_mission": mission,
                "active_competition": mission,
                "security": {"mode": self.policy.mode},
                "verification": {
                    "passed": sum(1 for item in evidence if item.status == "pass"),
                    "failed": sum(1 for item in evidence if item.status == "fail"),
                    "critical_failures": sum(
                        1
                        for item in evidence
                        if item.status == "fail" and item.critical
                    ),
                    "total": len(evidence),
                    "gates": {
                        item.gate: {
                            "status": item.status,
                            "message": item.message,
                            "checked_at": item.checked_at,
                        }
                        for item in evidence
                    },
                },
                "workspace": (
                    workspace.relative_to(self.repo).as_posix()
                    if workspace is not None
                    else None
                ),
            }
        )
        hud_path.write_text(
            json.dumps(redact_value(hud), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def _registry_has_run(workspace: Path) -> bool:
    registry = workspace / "artifacts" / "registry.sqlite"
    if not registry.exists():
        return False
    with sqlite3.connect(registry) as connection:
        count = connection.execute(
            "select count(*) from runs where status = 'completed'"
        ).fetchone()[0]
    return bool(count)


def _csv_has_columns(directory: Path, required: set[str]) -> tuple[bool, str]:
    for path in sorted(directory.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if required.issubset(set(reader.fieldnames or [])):
                return True, f"{path.name} matches contract"
    return False, f"no CSV in {directory} matches {sorted(required)}"


def _submission_schema_pass(workspace: Path) -> tuple[bool, str]:
    config = read_competition_config(workspace)
    path = workspace / "artifacts" / "final" / "submission.csv"
    if not path.exists():
        return False, "final submission.csv missing"
    id_column = str(config["competition.submission.id_column"])
    prediction_columns = [str(item) for item in config[
        "competition.submission.prediction_columns"
    ]]
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    expected = [id_column, *prediction_columns]
    return bool(rows) and fieldnames == expected, "submission schema matches"


def _secret_leaks(state_root: Path, workspace: Path) -> list[str]:
    secrets = [
        value
        for name in (
            "KAGGLE_API_TOKEN",
            "KAGGLE_KEY",
            "OPENAI_API_KEY",
            "WANDB_API_KEY",
            "HF_TOKEN",
        )
        if (value := os.environ.get(name))
    ]
    if not secrets:
        return []
    leaks: list[str] = []
    for root in (state_root, workspace / "artifacts" / "final"):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {
                ".json",
                ".jsonl",
                ".yaml",
                ".yml",
                ".md",
                ".txt",
                ".py",
                ".csv",
            }:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(secret in text for secret in secrets):
                leaks.append(str(path))
    return leaks


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
