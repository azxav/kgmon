from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

from kgmon_core.bootstrap import (
    CompetitionBootstrapper,
)
from kgmon_core.ensembles import EnsembleEngine
from kgmon_core.experiments import BaselineExperimentPlanner, ExperimentDagRunner
from kgmon_core.kaggle_bridge import SubmissionBridge
from kgmon_core.packaging import SubmissionPackager
from kgmon_core.profiling import CompetitionProfiler
from kgmon_core.registry import ArtifactRegistry
from kgmon_core.validation import ValidationPlanner
from kgmon_kaggle.adapter import KaggleAccessAdapter
from kgmon_kaggle.doctor import build_doctor_report
from kgmon_mcp.context import WorkspaceResolutionError, resolve_workspace
from kgmon_mcp.prompts import PROMPT_ID_MAP, internal_prompt_id
from kgmon_mcp.schemas import artifact_descriptor, failure, success
from kgmon_modes.workflows import WorkflowModeRunner
from kgmon_runtime.artifacts import descriptors_from_registry
from kgmon_runtime.doctor import RuntimeDoctor
from kgmon_runtime.dsml import (
    load_prompt_registry,
    load_skill_registry,
    run_prompt,
)
from kgmon_runtime.events import EventBus, EventType
from kgmon_runtime.redaction import redact_text
from kgmon_runtime.replay import SessionReplay
from kgmon_runtime.security import SecurityPolicy
from kgmon_runtime.setup import RuntimeSetup
from kgmon_runtime.state import RuntimeState
from kgmon_runtime.verification import VerificationEngine

COMPETITION_RESOURCES = (
    "competition://current/manifest",
    "competition://current/profile",
    "competition://current/validation",
    "competition://current/runs",
    "competition://current/artifacts",
    "competition://current/kaggle-pages",
    "competition://current/final-package",
)

KGMON_RESOURCES = (
    "kgmon://state/current",
    "kgmon://mission/current",
    "kgmon://hud/current",
    "kgmon://competition/current/manifest",
    "kgmon://competition/current/profile",
    "kgmon://competition/current/validation",
    "kgmon://competition/current/runs",
    "kgmon://competition/current/artifacts",
    "kgmon://competition/current/final-package",
    "kgmon://logs/events",
)

RESOURCES = COMPETITION_RESOURCES + KGMON_RESOURCES

COMPETITION_TOOLS = (
    "kgmon.competition.bootstrap",
    "kgmon.competition.audit_rules",
    "kgmon.kaggle.doctor",
    "kgmon.data.profile",
    "kgmon.validation.plan",
    "kgmon.experiment.plan",
    "kgmon.experiment.run",
    "kgmon.experiment.status",
    "kgmon.artifacts.list",
    "kgmon.ensemble.search",
    "kgmon.submission.package",
    "kgmon.report.generate",
)

KGMON_TOOLS = (
    "kgmon.setup",
    "kgmon.doctor",
    "kgmon.bootstrap",
    "kgmon.deep_interview",
    "kgmon.ralplan",
    "kgmon.team.run",
    "kgmon.ralph.run",
    "kgmon.ultrawork.run",
    "kgmon.autopilot.run",
    "kgmon.verify.all",
    "kgmon.hud.get",
    "kgmon.replay.session",
    "kgmon.package.final",
    "kgmon.submit.final",
)

TOOLS = COMPETITION_TOOLS + KGMON_TOOLS

MCP_RESOURCE_URIS = (
    "kgmon://state/current",
    "kgmon://hud/current",
    "kgmon://mission/current",
    "kgmon://competition/current/manifest",
    "kgmon://competition/current/profile",
    "kgmon://competition/current/validation",
    "kgmon://competition/current/runs",
    "kgmon://competition/current/artifacts",
    "kgmon://competition/current/final-package",
    "kgmon://logs/events",
)

PUBLIC_TOOL_MAP: dict[str, str] = {
    "kgmon_doctor": "kgmon.doctor",
    "kgmon_bootstrap_competition": "kgmon.competition.bootstrap",
    "kgmon_data_profile": "kgmon.data.profile",
    "kgmon_validation_plan": "kgmon.validation.plan",
    "kgmon_leakage_audit": "kgmon.competition.audit_rules",
    "kgmon_experiment_plan": "kgmon.experiment.plan",
    "kgmon_experiment_run": "kgmon.experiment.run",
    "kgmon_experiment_status": "kgmon.experiment.status",
    "kgmon_artifacts_list": "kgmon.artifacts.list",
    "kgmon_ensemble_search": "kgmon.ensemble.search",
    "kgmon_package_final": "kgmon.package.final",
    "kgmon_verify_all": "kgmon.verify.all",
    "kgmon_hud_get": "kgmon.hud.get",
    "kgmon_competition_audit_rules": "kgmon.competition.audit_rules",
    "kgmon_kaggle_doctor": "kgmon.kaggle.doctor",
    "kgmon_status_get": "kgmon.status.get",
}

CUSTOM_PUBLIC_TOOLS = (
    "kgmon_skills_list",
    "kgmon_prompts_list",
    "kgmon_prompt_run",
)

PUBLIC_TOOLS = tuple(sorted((*PUBLIC_TOOL_MAP.keys(), *CUSTOM_PUBLIC_TOOLS)))


def list_resources() -> list[str]:
    return list(RESOURCES)


def list_tools() -> list[str]:
    return list(TOOLS)


def list_public_tools() -> list[str]:
    return list(PUBLIC_TOOLS)


def public_tool_schemas() -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for name in PUBLIC_TOOLS:
        properties: dict[str, dict[str, Any]] = {
            "workspace_root": {
                "type": "string",
                "description": "Optional KGMON workspace root.",
            }
        }
        required: list[str] = []
        if name == "kgmon_bootstrap_competition":
            properties["slug"] = {"type": "string"}
            required.append("slug")
        elif name == "kgmon_experiment_plan":
            properties["mode"] = {"type": "string"}
        elif name == "kgmon_experiment_run":
            properties["dag"] = {"type": "string"}
        elif name == "kgmon_prompt_run":
            properties["prompt_id"] = {"type": "string"}
            required.append("prompt_id")
        schemas[name] = {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }
    return schemas


def public_tool_definitions() -> list[dict[str, Any]]:
    schemas = public_tool_schemas()
    return [
        {
            "name": name,
            "description": _tool_description(name),
            "inputSchema": schemas[name],
        }
        for name in PUBLIC_TOOLS
    ]


def list_mcp_resources() -> list[dict[str, Any]]:
    return [
        {
            "uri": uri,
            "name": uri.removeprefix("kgmon://"),
            "mimeType": "application/json",
        }
        for uri in MCP_RESOURCE_URIS
    ]


def list_mcp_prompts() -> list[dict[str, Any]]:
    return [
        {"name": name, "description": f"KGMON DS/ML prompt: {internal_id}"}
        for name, internal_id in sorted(PROMPT_ID_MAP.items())
    ]


def read_mcp_resource(uri: str, *, workspace_root: str | None = None) -> dict[str, Any]:
    try:
        workspace = resolve_workspace(workspace_root=workspace_root)
        return success(read_resource(uri, workspace=workspace))
    except WorkspaceResolutionError as exc:
        return failure(exc.code, exc.message)
    except Exception as exc:
        return failure("RESOURCE_READ_FAILED", str(exc))


def run_public_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in PUBLIC_TOOLS:
        return failure(
            "UNKNOWN_TOOL",
            f"unknown tool: {name}",
            next_actions=["kgmon_tools_list"],
        )
    try:
        workspace = resolve_workspace(
            workspace_root=_string_or_none(arguments.get("workspace_root"))
        )
    except WorkspaceResolutionError as exc:
        return failure(exc.code, exc.message)

    try:
        if name == "kgmon_skills_list":
            return success(load_skill_registry(workspace / ".kgmon"))
        if name == "kgmon_prompts_list":
            registry = load_prompt_registry(workspace / ".kgmon")
            return success(
                {
                    **registry,
                    "public_prompts": [
                        {"id": public_id, "internal_id": internal_id}
                        for public_id, internal_id in sorted(PROMPT_ID_MAP.items())
                    ],
                }
            )
        if name == "kgmon_prompt_run":
            public_prompt_id = str(arguments.get("prompt_id", ""))
            content, artifact = run_prompt(
                workspace / ".kgmon", internal_prompt_id(public_prompt_id)
            )
            return success(
                {"prompt_id": public_prompt_id, "content": content},
                artifacts=[
                    artifact_descriptor(
                        artifact,
                        kind="prompt_run",
                        workspace=workspace,
                        mime_type="text/markdown",
                    )
                ],
            )
        if name == "kgmon_status_get":
            return success(read_resource("kgmon://state/current", workspace=workspace))

        internal_name = PUBLIC_TOOL_MAP[name]
        internal_args = _translate_public_arguments(name, arguments, workspace)
        return success(run_tool(internal_name, internal_args))
    except KeyError as exc:
        return failure("TOOL_CONTRACT_ERROR", str(exc))
    except Exception as exc:
        return failure("TOOL_EXECUTION_FAILED", str(exc))


def create_mcp_server() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception:
        return None

    mcp = FastMCP("kgmon")

    for definition in public_tool_definitions():
        tool_name = str(definition["name"])
        mcp.tool(name=tool_name)(_make_fastmcp_tool(tool_name))

    return mcp


def _make_fastmcp_tool(tool_name: str) -> Any:
    def tool(
        workspace_root: str = "",
        prompt_id: str = "",
        slug: str = "",
        mode: str = "",
        dag: str = "",
    ) -> dict[str, Any]:
        args = {
            "workspace_root": workspace_root,
            "prompt_id": prompt_id,
            "slug": slug,
            "mode": mode,
            "dag": dag,
        }
        return run_public_tool(tool_name, args)

    tool.__name__ = tool_name
    return tool


def read_resource(uri: str, *, workspace: Path) -> dict[str, Any]:
    state_root = _state_root(workspace)
    if uri == "kgmon://state/current":
        return _read_json_resource(state_root / "runtime-config.json")
    if uri == "kgmon://mission/current":
        active = _read_json_resource(
            state_root / "state" / "active-competition.json"
        )
        mission = active.get("mission")
        if isinstance(mission, str):
            return _read_json_resource(
                state_root / "state" / "missions" / f"{mission}.json"
            )
        return {}
    if uri == "kgmon://hud/current":
        return _read_json_resource(state_root / "hud" / "current.json")
    if uri == "kgmon://logs/events":
        return {
            "content": redact_text(
                _read_text(state_root / "logs" / "events.jsonl")
            )
        }
    if uri == "kgmon://competition/current/manifest":
        uri = "competition://current/manifest"
    elif uri == "kgmon://competition/current/profile":
        uri = "competition://current/profile"
    elif uri == "kgmon://competition/current/validation":
        uri = "competition://current/validation"
    elif uri == "kgmon://competition/current/runs":
        uri = "competition://current/runs"
    elif uri == "kgmon://competition/current/artifacts":
        uri = "competition://current/artifacts"
    elif uri == "kgmon://competition/current/final-package":
        uri = "competition://current/final-package"

    if uri == "competition://current/manifest":
        return {
            "content": redact_text(
                _read_text(workspace / "configs" / "competition.yaml")
            )
        }
    if uri == "competition://current/profile":
        return _read_json_resource(workspace / "artifacts" / "reports" / "profile.json")
    if uri == "competition://current/validation":
        return {
            "content": redact_text(
                _read_text(workspace / "configs" / "validation.yaml")
            )
        }
    if uri == "competition://current/artifacts":
        artifacts = ArtifactRegistry(workspace).list_artifacts()
        return {"artifacts": [artifact.__dict__ for artifact in artifacts]}
    if uri == "competition://current/runs":
        return {
            "content": redact_text(
                _read_text(workspace / "configs" / "experiments.yaml")
            )
        }
    if uri == "competition://current/kaggle-pages":
        pages = []
        for path in sorted((workspace / "kaggle" / "pages").glob("*.md")):
            pages.append(
                {
                    "name": path.name,
                    "content": redact_text(path.read_text(encoding="utf-8")),
                }
            )
        return {"pages": pages}
    if uri == "competition://current/final-package":
        final_dir = workspace / "artifacts" / "final"
        return {
            "files": sorted(path.name for path in final_dir.iterdir() if path.is_file())
        }
    raise KeyError(f"unknown resource: {uri}")


def run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    workspace = Path(str(arguments.get("workspace", ".")))
    if name == "kgmon.setup":
        result = RuntimeSetup(workspace).setup_local(
            repair=bool(arguments.get("repair", False))
        )
        return {
            "status": "completed",
            "state_root": str(result.state_root),
            "config_path": str(result.config_path),
            "mcp_path": str(result.mcp_path),
        }
    if name == "kgmon.doctor":
        runtime_report = RuntimeDoctor(workspace).check()
        return {
            "status": "ok" if runtime_report.ok else "failed",
            "messages": runtime_report.messages,
        }
    if name == "kgmon.hud.get":
        return read_resource("kgmon://hud/current", workspace=workspace)
    if name == "kgmon.bootstrap":
        RuntimeSetup(workspace).setup_local()
        slug = str(arguments["slug"])
        bus = EventBus(workspace / ".kgmon")
        session_id = bus.start_session(command=f"kgmon.bootstrap {slug}")
        bus.emit(
            EventType.BEFORE_TOOL_CALL,
            session_id=session_id,
            mission=slug,
            payload={"tool": "kgmon.bootstrap", "slug": slug},
        )
        bootstrap_result = CompetitionBootstrapper(
            adapter=KaggleAccessAdapter(),
            workspace_root=workspace,
        ).bootstrap(slug)
        descriptors = descriptors_from_registry(bootstrap_result.workspace)
        mission = RuntimeState(workspace).record_bootstrap(
            mission_name=slug,
            competition_slug=slug,
            workspace=bootstrap_result.workspace,
            session_id=session_id,
            artifacts=descriptors,
        )
        bus.emit(
            EventType.DATA_DOWNLOADED,
            session_id=session_id,
            mission=slug,
            payload={
                "downloaded_files": bootstrap_result.downloaded_files,
                "artifact_descriptors": mission.artifact_count,
            },
        )
        bus.emit(
            EventType.AFTER_TOOL_CALL,
            session_id=session_id,
            mission=slug,
            payload={"tool": "kgmon.bootstrap", "status": "completed"},
        )
        return {
            "slug": bootstrap_result.slug,
            "workspace": str(bootstrap_result.workspace),
            "session_id": session_id,
            "artifact_descriptors": mission.artifact_count,
            "status": "completed",
        }
    if name in {
        "kgmon.deep_interview",
        "kgmon.ralplan",
        "kgmon.team.run",
        "kgmon.ralph.run",
        "kgmon.ultrawork.run",
        "kgmon.autopilot.run",
    }:
        return WorkflowModeRunner(workspace).run_mcp_tool(name, arguments)
    elif name == "kgmon.package.final":
        name = "kgmon.submission.package"

    if name == "kgmon.kaggle.doctor":
        doctor_report = build_doctor_report(
            ("kagglehub", "kaggle", "python-dotenv", "requests"),
            __import__("sys").version_info,
            vendor_available=(Path.cwd() / "vendor" / "kaggle-skill").exists(),
        )
        return {"report": redact_text(doctor_report.to_text())}
    if name == "kgmon.competition.bootstrap":
        slug = str(arguments["slug"])
        bootstrap_result = CompetitionBootstrapper(
            adapter=KaggleAccessAdapter(),
            workspace_root=workspace,
        ).bootstrap(slug)
        return {
            "slug": bootstrap_result.slug,
            "workspace": str(bootstrap_result.workspace),
            "status": "completed",
        }
    if name == "kgmon.data.profile":
        profile_result = CompetitionProfiler(workspace).profile()
        return {"status": "completed", "profile_path": str(profile_result.profile_path)}
    if name == "kgmon.validation.plan":
        validation_result = ValidationPlanner(workspace).plan()
        status = "blocked" if validation_result.leakage_blocked else "completed"
        return {"status": status}
    if name == "kgmon.experiment.plan":
        plan_result = BaselineExperimentPlanner(workspace).plan(
            mode=str(arguments.get("mode", "baseline"))
        )
        return {
            "status": "completed",
            "experiments_path": str(plan_result.experiments_path),
        }
    if name == "kgmon.experiment.run":
        dag = arguments.get("dag")
        dag_result = ExperimentDagRunner(workspace).run(Path(str(dag)) if dag else None)
        return {
            "job_id": f"kgmon-experiment-run-{workspace.name}",
            "status": "completed" if not dag_result.failed else "failed",
            "completed": dag_result.completed,
            "failed": dag_result.failed,
        }
    if name == "kgmon.artifacts.list":
        artifacts = ArtifactRegistry(workspace).list_artifacts()
        return {"artifacts": [artifact.__dict__ for artifact in artifacts]}
    if name == "kgmon.ensemble.search":
        ensemble_result = EnsembleEngine(workspace).search()
        return {
            "status": "completed",
            "submission_path": str(ensemble_result.submission_path),
        }
    if name == "kgmon.submission.package":
        package_result = SubmissionPackager(workspace).package_final()
        return {"status": "completed", "final_dir": str(package_result.final_dir)}
    if name == "kgmon.verify.all":
        report = VerificationEngine(workspace).verify_all()
        return {
            "status": "completed" if report.ok else "failed",
            "passed": report.passed,
            "failed": report.failed,
            "critical_failures": report.critical_failures,
            "evidence_path": str(report.evidence_path),
            "session_id": report.session_id,
            "gates": [
                {"gate": evidence.gate, "status": evidence.status}
                for evidence in report.evidence
            ],
        }
    if name == "kgmon.submit.final":
        policy = SecurityPolicy.for_repo(workspace)
        try:
            submission_result = SubmissionBridge(
                Path(str(arguments["competition_workspace"])),
                KaggleAccessAdapter(),
            ).submit_final(
                require_confirmation=bool(
                    arguments.get("require_confirmation", True)
                ),
                confirmed=bool(arguments.get("confirm", False)),
            )
        except RuntimeError as exc:
            policy.log("submission_blocked", {"error": str(exc)})
            return {"status": "blocked", "message": str(exc)}
        return {
            "status": submission_result.status,
            "archive_path": str(submission_result.archive_path),
        }
    if name in {
        "kgmon.experiment.status",
        "kgmon.report.generate",
        "kgmon.competition.audit_rules",
    }:
        return {"status": "not_implemented_for_mcp_stub"}
    if name == "kgmon.replay.session":
        replay = SessionReplay(workspace / ".kgmon").summarize(
            str(arguments.get("session", "latest"))
        )
        return {
            "session_id": replay.session_id,
            "command": replay.command,
            "event_types": replay.event_types,
            "event_count": replay.event_count,
        }
    raise KeyError(f"unknown tool: {name}")


def _translate_public_arguments(
    name: str, arguments: dict[str, Any], workspace: Path
) -> dict[str, Any]:
    translated = dict(arguments)
    translated["workspace"] = str(workspace)
    translated.pop("workspace_root", None)
    if name == "kgmon_bootstrap_competition" and "competition_slug" in translated:
        translated["slug"] = translated.pop("competition_slug")
    if name == "kgmon_package_final" and "competition_workspace" in translated:
        translated["workspace"] = str(translated["competition_workspace"])
    return translated


def _tool_description(name: str) -> str:
    descriptions = {
        "kgmon_doctor": "Check KGMON runtime health.",
        "kgmon_bootstrap_competition": "Bootstrap a Kaggle competition workspace.",
        "kgmon_data_profile": "Profile the current competition data.",
        "kgmon_validation_plan": "Create the validation plan.",
        "kgmon_leakage_audit": "Audit competition rules and leakage constraints.",
        "kgmon_experiment_plan": "Create an experiment plan.",
        "kgmon_experiment_run": "Run planned experiments.",
        "kgmon_experiment_status": "Return experiment status.",
        "kgmon_artifacts_list": "List artifact descriptors.",
        "kgmon_ensemble_search": "Run ensemble search.",
        "kgmon_package_final": "Package the final submission bundle.",
        "kgmon_verify_all": "Run all verification gates.",
        "kgmon_hud_get": "Return the current KGMON HUD.",
        "kgmon_skills_list": "List installed KGMON DS/ML skills.",
        "kgmon_prompts_list": "List installed KGMON DS/ML prompts.",
        "kgmon_prompt_run": "Render a KGMON DS/ML prompt.",
        "kgmon_competition_audit_rules": "Audit competition rules.",
        "kgmon_kaggle_doctor": "Run Kaggle access diagnostics.",
        "kgmon_status_get": "Return the current KGMON runtime status.",
    }
    return descriptions.get(name, "KGMON MCP tool.")


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def main() -> None:
    print(json.dumps({"resources": list_resources(), "tools": list_tools()}, indent=2))


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _read_json_resource(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return cast(
        dict[str, Any],
        json.loads(redact_text(path.read_text(encoding="utf-8"))),
    )


def _state_root(workspace: Path | None = None) -> Path:
    if workspace is not None and (workspace / ".kgmon").exists():
        return workspace / ".kgmon"
    return Path(os.environ.get("KGMON_STATE_ROOT", ".kgmon"))

if __name__ == "__main__":
    main()
