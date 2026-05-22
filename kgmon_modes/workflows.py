from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from kgmon_agents.registry import AgentRegistry
from kgmon_runtime.dsml import CORE_RULES, build_team_route
from kgmon_runtime.events import EventBus, EventType
from kgmon_runtime.setup import RuntimeSetup

MAX_ITERATIONS = 5
MAX_PARALLEL_WORKERS = 5


@dataclass(frozen=True)
class ModeRunResult:
    mode: str
    mission: str
    session_id: str
    handoff_path: Path
    status: str


class WorkflowModeRunner:
    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.state_root = repo / ".kgmon"
        self.registry = AgentRegistry.default()

    def deep_interview(self, competition_slug: str) -> ModeRunResult:
        mission = competition_slug
        handoff = {
            "type": "mission_brief",
            "competition_slug": competition_slug,
            "workspace": f"competitions/{competition_slug}",
            "acceptance_gates": [
                "KAGGLE_RULES_AUDITED",
                "DATA_PROFILE_EXISTS",
                "VALIDATION_FIXED",
            ],
        }
        return self._record_mode(
            mode="deep-interview",
            mission=mission,
            competition_slug=competition_slug,
            status="interviewed",
            handoff=handoff,
        )

    def ralplan(self, mission: str) -> ModeRunResult:
        mode_dir = self._mode_dir(mission, "ralplan")
        outputs = {
            "plan.md": (
                f"# {mission} Plan\n\n"
                "Follow scout -> analyst -> architect -> critic.\n"
            ),
            "plan.json": json.dumps(
                {
                    "schema_version": 1,
                    "mission": mission,
                    "pipeline": [
                        "scout",
                        "analyst",
                        "architect",
                        "critic",
                        "planner",
                        "critic",
                        "approved_plan",
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "decision_log.md": "# Decision Log\n\n- Use bounded artifact handoffs.\n",
            "risk_register.md": "# Risk Register\n\n- Submission remains guarded.\n",
            "acceptance_gates.yaml": (
                "gates:\n"
                "  - CONFIG_VALID\n"
                "  - KAGGLE_RULES_AUDITED\n"
            ),
        }
        for name, content in outputs.items():
            self._write_text(mode_dir / name, content)
        handoff = {
            "type": "plan_bundle",
            "pipeline": [
                "scout",
                "analyst",
                "architect",
                "critic",
                "planner",
                "critic",
                "approved_plan",
            ],
            "artifacts": [
                self._artifact_descriptor(path, artifact_type="plan_artifact")
                for path in sorted(mode_dir.iterdir())
            ],
        }
        return self._record_mode(
            mode="ralplan",
            mission=mission,
            competition_slug=self._competition_for(mission),
            status="planned",
            handoff=handoff,
        )

    def team(self, assignment_spec: str, task: str) -> ModeRunResult:
        mission = self._active_mission()
        allocated = self.registry.allocate(assignment_spec)
        role = allocated[0]
        assignment_dir = self.state_root / "state" / "team" / mission
        self._write_json(
            assignment_dir / f"{role.key}.json",
            {
                "schema_version": 1,
                "mission": mission,
                "role": role.to_json(),
                "worker_count": len(allocated),
                "task_digest": _digest(task),
            },
        )
        handoff = {
            "type": "team_assignment",
            "assignment": {
                "role": role.id,
                "count": len(allocated),
                "task_digest": _digest(task),
                "permitted_tools": list(role.permitted_tools),
                "output_artifact_types": list(role.output_artifact_types),
                "verification_obligations": list(role.verification_obligations),
                "may_write_final_artifacts": role.may_write_final_artifacts,
            },
        }
        return self._record_mode(
            mode="team",
            mission=mission,
            competition_slug=self._competition_for(mission),
            status="team_assigned",
            handoff=handoff,
        )

    def dsml_team_route(self) -> ModeRunResult:
        mission = self._active_mission()
        route_path = build_team_route(self.state_root, mission)
        handoff = {
            "type": "dsml_team_route",
            "domain": "dsml",
            "route": route_path.relative_to(self.state_root).as_posix(),
            "core_rules": list(CORE_RULES),
            "artifacts": [
                self._artifact_descriptor(route_path, artifact_type="team_route")
            ],
        }
        return self._record_mode(
            mode="team",
            mission=mission,
            competition_slug=self._competition_for(mission),
            status="dsml_team_routed",
            handoff=handoff,
        )

    def ralph(self, task: str) -> ModeRunResult:
        mission = self._active_mission()
        handoff = {
            "type": "completion_loop",
            "loop": ["execute", "verify", "diagnose", "fix", "verify"],
            "task_digest": _digest(task),
            "limits": {"max_iterations": MAX_ITERATIONS},
            "verification_handoff": {
                "required_evidence": "fresh",
                "critical_failures_allowed": 0,
            },
        }
        return self._record_mode(
            mode="ralph",
            mission=mission,
            competition_slug=self._competition_for(mission),
            status="completion_loop_ready",
            handoff=handoff,
        )

    def ultrawork(self, task: str) -> ModeRunResult:
        mission = self._active_mission()
        lanes = [
            "lane_tabular_gbdt",
            "lane_neural",
            "lane_feature_engineering",
            "lane_validation_audit",
            "lane_ensemble",
        ]
        handoff = {
            "type": "parallel_lanes",
            "lanes": lanes,
            "task_digest": _digest(task),
            "limits": {"max_parallel_workers": MAX_PARALLEL_WORKERS},
        }
        return self._record_mode(
            mode="ultrawork",
            mission=mission,
            competition_slug=self._competition_for(mission),
            status="parallel_lanes_ready",
            handoff=handoff,
        )

    def autopilot(self, competition_slug: str) -> ModeRunResult:
        handoff = {
            "type": "autopilot_plan",
            "competition_slug": competition_slug,
            "pipeline": [
                "bootstrap",
                "deep-interview",
                "ralplan",
                "team",
                "ralph",
                "verify",
                "package",
            ],
            "submission_guard": _submission_guard(),
        }
        return self._record_mode(
            mode="autopilot",
            mission=competition_slug,
            competition_slug=competition_slug,
            status="autopilot_ready",
            handoff=handoff,
        )

    def run_mcp_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "kgmon.deep_interview":
            result = self.deep_interview(str(arguments["slug"]))
        elif name == "kgmon.ralplan":
            result = self.ralplan(str(arguments["mission"]))
        elif name == "kgmon.team.run":
            result = self.team(
                str(arguments["assignment"]),
                str(arguments.get("task", "")),
            )
        elif name == "kgmon.ralph.run":
            result = self.ralph(str(arguments.get("task", "")))
        elif name == "kgmon.ultrawork.run":
            result = self.ultrawork(str(arguments.get("task", "")))
        elif name == "kgmon.autopilot.run":
            result = self.autopilot(str(arguments["slug"]))
        else:
            raise KeyError(f"unknown workflow tool: {name}")
        return {
            "status": result.status,
            "mode": result.mode,
            "mission": result.mission,
            "session_id": result.session_id,
            "handoff_path": str(result.handoff_path),
        }

    def _record_mode(
        self,
        *,
        mode: str,
        mission: str,
        competition_slug: str,
        status: str,
        handoff: dict[str, Any],
    ) -> ModeRunResult:
        RuntimeSetup(self.repo).setup_local()
        bus = EventBus(self.state_root)
        session_id = bus.start_session(command=f"kgx {mode} {mission}")
        bus.emit(
            EventType.BEFORE_COMMAND,
            session_id=session_id,
            mission=mission,
            payload={"command": mode, "mission": mission},
        )
        handoff_path = self._append_handoff(
            mission=mission,
            mode=mode,
            handoff=handoff,
        )
        mission_record = self._mission_record(mission)
        mode_history = _string_list(mission_record.get("mode_history"))
        mode_history.append(mode)
        mission_payload = {
            "schema_version": 1,
            "name": mission,
            "competition_slug": competition_slug,
            "status": status,
            "workspace": f"competitions/{competition_slug}",
            "mode_history": mode_history,
            "handoff_path": handoff_path.relative_to(self.state_root).as_posix(),
            "limits": {
                "max_iterations": MAX_ITERATIONS,
                "max_parallel_workers": MAX_PARALLEL_WORKERS,
            },
            "submission_guard": _submission_guard(),
            "session_id": session_id,
        }
        self._write_json(
            self.state_root / "state" / "missions" / f"{mission}.json",
            mission_payload,
        )
        self._write_json(
            self.state_root / "state" / "active-competition.json",
            {
                "schema_version": 1,
                "slug": competition_slug,
                "workspace": f"competitions/{competition_slug}",
                "mission": mission,
            },
        )
        self._write_json(
            self.state_root / "state" / "active-mode.json",
            {"schema_version": 1, "mode": mode, "mission": mission},
        )
        self._write_json(
            self.state_root / "hud" / "current.json",
            self._hud_payload(
                mission=mission,
                competition_slug=competition_slug,
                mode=mode,
                status=status,
                handoff_path=handoff_path,
            ),
        )
        bus.emit(
            EventType.AFTER_COMMAND,
            session_id=session_id,
            mission=mission,
            payload={"command": mode, "status": status},
        )
        return ModeRunResult(
            mode=mode,
            mission=mission,
            session_id=session_id,
            handoff_path=handoff_path,
            status=status,
        )

    def _append_handoff(
        self,
        *,
        mission: str,
        mode: str,
        handoff: dict[str, Any],
    ) -> Path:
        path = self.state_root / "missions" / mission / "handoffs.json"
        payload = self._read_json(path)
        handoffs = _dict_list(payload.get("handoffs"))
        entry: dict[str, Any] = {
            "schema_version": 1,
            "mode": mode,
            "created_at": _utc_now(),
            "handoff": handoff,
        }
        if "assignment" in handoff:
            entry["assignment"] = handoff["assignment"]
        handoffs.append(entry)
        self._write_json(
            path,
            {"schema_version": 1, "mission": mission, "handoffs": handoffs},
        )
        return path

    def _hud_payload(
        self,
        *,
        mission: str,
        competition_slug: str,
        mode: str,
        status: str,
        handoff_path: Path,
    ) -> dict[str, Any]:
        handoffs = self._read_json(handoff_path)
        team_assignment: dict[str, Any] | None = None
        for entry in reversed(_dict_list(handoffs.get("handoffs"))):
            assignment = entry.get("assignment")
            if isinstance(assignment, dict):
                team_assignment = cast(dict[str, Any], assignment)
                break
        return {
            "schema_version": 1,
            "active_mode": mode,
            "active_competition": competition_slug,
            "active_mission": mission,
            "security": {"mode": "standard"},
            "workflow": {
                "status": status,
                "handoff_path": handoff_path.relative_to(self.state_root).as_posix(),
            },
            "team": {"last_assignment": team_assignment},
            "submission": _submission_guard(),
        }

    def _active_mission(self) -> str:
        active = self._read_json(self.state_root / "state" / "active-competition.json")
        mission = active.get("mission") or active.get("slug")
        if not isinstance(mission, str) or not mission:
            raise ValueError(
                "no active mission; run kgx deep-interview or bootstrap first"
            )
        return mission

    def _competition_for(self, mission: str) -> str:
        record = self._mission_record(mission)
        competition = record.get("competition_slug")
        if isinstance(competition, str) and competition:
            return competition
        active = self._read_json(self.state_root / "state" / "active-competition.json")
        slug = active.get("slug")
        return str(slug) if isinstance(slug, str) and slug else mission

    def _mission_record(self, mission: str) -> dict[str, Any]:
        return self._read_json(
            self.state_root / "state" / "missions" / f"{mission}.json"
        )

    def _mode_dir(self, mission: str, mode: str) -> Path:
        path = self.state_root / "missions" / mission / mode
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _artifact_descriptor(self, path: Path, *, artifact_type: str) -> dict[str, Any]:
        relative = path.relative_to(self.state_root).as_posix()
        return {
            "type": artifact_type,
            "path": relative,
            "hash": _file_hash(path),
            "uri": f"kgmon://mission/current/{relative}",
        }

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _submission_guard() -> dict[str, object]:
    return {"auto_submit": "blocked", "requires_confirmation": True}


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [cast(dict[str, Any], item) for item in value if isinstance(item, dict)]
