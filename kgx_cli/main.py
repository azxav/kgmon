from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

import typer

from kgmon_core.bootstrap import CompetitionBootstrapper
from kgmon_core.kaggle_bridge import SubmissionBridge
from kgmon_core.packaging import SubmissionPackager
from kgmon_kaggle.adapter import KaggleAccessAdapter
from kgmon_modes.workflows import WorkflowModeRunner
from kgmon_runtime.artifacts import descriptors_from_registry
from kgmon_runtime.doctor import RuntimeDoctor, RuntimeDoctorReport
from kgmon_runtime.dsml import (
    load_skill_registry,
    render_skill_inspection,
    run_prompt,
)
from kgmon_runtime.events import EventBus, EventType
from kgmon_runtime.mcp_config import (
    SUPPORTED_MCP_CLIENTS,
    doctor_client_config,
    install_client_config,
)
from kgmon_runtime.replay import SessionReplay
from kgmon_runtime.security import SecurityPolicy
from kgmon_runtime.setup import RuntimeSetup
from kgmon_runtime.state import RuntimeState
from kgmon_runtime.verification import VerificationEngine

app = typer.Typer(help="KGMON-Codex OMC-style runtime launcher.")
doctor_app = typer.Typer(help="Runtime health and conflict diagnostics.")
package_app = typer.Typer(help="Final package operations.")
verify_app = typer.Typer(help="Verification gate operations.")
skills_app = typer.Typer(help="Installed KGMON skill packs.")
prompt_app = typer.Typer(help="Installed KGMON prompt templates.")
mcp_app = typer.Typer(help="STDIO MCP client configuration.")


@app.callback()
def main() -> None:
    """Run the kgx runtime launcher."""


@app.command("setup")
def setup(
    local: Annotated[
        bool,
        typer.Option("--local", help="Create local .kgmon runtime state."),
    ] = False,
    repair: Annotated[
        bool,
        typer.Option("--repair", help="Repair managed runtime files."),
    ] = False,
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to configure."),
    ] = Path("."),
) -> None:
    """Create or repair the local OMC-style runtime skeleton."""
    if not local and not repair:
        typer.echo("Pass --local or --repair.")
        raise typer.Exit(code=1)

    result = RuntimeSetup(repo).setup_local(repair=repair)
    action = "Repaired" if repair else "Created"
    typer.echo(f"{action} KGMON runtime state root: {result.state_root}")
    typer.echo(f"Runtime config: {result.config_path}")
    typer.echo(f"MCP config: {result.mcp_path}")


@app.command("bootstrap")
def bootstrap(
    competition_slug: Annotated[str, typer.Argument(help="Kaggle competition slug.")],
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to configure."),
    ] = Path("."),
) -> None:
    """Bootstrap a competition and persist resumable mission state."""
    RuntimeSetup(repo).setup_local()
    state_root = repo / ".kgmon"
    bus = EventBus(state_root)
    session_id = bus.start_session(command=f"kgx bootstrap {competition_slug}")
    bus.emit(
        EventType.BEFORE_COMMAND,
        session_id=session_id,
        mission=competition_slug,
        payload={"command": "bootstrap", "competition_slug": competition_slug},
    )
    try:
        bootstrap_result = CompetitionBootstrapper(
            adapter=KaggleAccessAdapter(),
            workspace_root=repo,
        ).bootstrap(competition_slug)
        descriptors = descriptors_from_registry(bootstrap_result.workspace)
        mission = RuntimeState(repo).record_bootstrap(
            mission_name=competition_slug,
            competition_slug=competition_slug,
            workspace=bootstrap_result.workspace,
            session_id=session_id,
            artifacts=descriptors,
        )
        bus.emit(
            EventType.DATA_DOWNLOADED,
            session_id=session_id,
            mission=competition_slug,
            payload={
                "downloaded_files": bootstrap_result.downloaded_files,
                "artifact_descriptors": mission.artifact_count,
            },
        )
        bus.emit(
            EventType.AFTER_COMMAND,
            session_id=session_id,
            mission=competition_slug,
            payload={"command": "bootstrap", "status": "completed"},
        )
    except Exception as exc:
        bus.emit(
            EventType.AFTER_COMMAND,
            session_id=session_id,
            mission=competition_slug,
            payload={"command": "bootstrap", "status": "failed", "error": str(exc)},
        )
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc

    typer.echo(f"Bootstrapped KGMON mission: {mission.name}")
    typer.echo(f"Workspace: {mission.workspace}")
    typer.echo(f"Artifact descriptors: {mission.artifact_count}")
    typer.echo(f"Session: {session_id}")


@app.command("deep-interview")
def deep_interview(
    competition_slug: Annotated[str, typer.Argument(help="Kaggle competition slug.")],
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to configure."),
    ] = Path("."),
) -> None:
    """Convert a Kaggle slug into an execution-ready mission."""
    result = WorkflowModeRunner(repo).deep_interview(competition_slug)
    _emit_mode_result(result.mode, result.mission, result.handoff_path)


@app.command("ralplan")
def ralplan(
    mission_name: Annotated[str, typer.Argument(help="Mission name to plan.")],
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to configure."),
    ] = Path("."),
) -> None:
    """Run the OMC-style consensus planning pipeline."""
    result = WorkflowModeRunner(repo).ralplan(mission_name)
    _emit_mode_result(result.mode, result.mission, result.handoff_path)


@app.command("team")
def team(
    assignment: Annotated[
        str | None,
        typer.Argument(help='Worker spec, e.g. "4:modeler".'),
    ] = None,
    task: Annotated[
        str | None,
        typer.Argument(help="Bounded worker task."),
    ] = None,
    domain: Annotated[
        str | None,
        typer.Option("--domain", help="Route a domain workflow, e.g. dsml."),
    ] = None,
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to configure."),
    ] = Path("."),
) -> None:
    """Allocate a role lane or route a DS/ML team workflow."""
    runner = WorkflowModeRunner(repo)
    if domain == "dsml":
        result = runner.dsml_team_route()
    elif assignment is not None and task is not None:
        result = runner.team(assignment, task)
    else:
        typer.echo('Pass ASSIGNMENT and TASK, or use "--domain dsml".')
        raise typer.Exit(code=1)
    _emit_mode_result(result.mode, result.mission, result.handoff_path)


@app.command("ralph")
def ralph(
    task: Annotated[str, typer.Argument(help="Persistent completion-loop task.")],
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to configure."),
    ] = Path("."),
) -> None:
    """Prepare the execute-verify-diagnose-fix-verify loop."""
    result = WorkflowModeRunner(repo).ralph(task)
    _emit_mode_result(result.mode, result.mission, result.handoff_path)


@app.command("ultrawork")
def ultrawork(
    task: Annotated[str, typer.Argument(help="Parallel experiment burst task.")],
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to configure."),
    ] = Path("."),
) -> None:
    """Prepare bounded parallel KGMON experiment lanes."""
    result = WorkflowModeRunner(repo).ultrawork(task)
    _emit_mode_result(result.mode, result.mission, result.handoff_path)


@app.command("autopilot")
def autopilot(
    competition_slug: Annotated[str, typer.Argument(help="Kaggle competition slug.")],
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to configure."),
    ] = Path("."),
) -> None:
    """Prepare autonomous orchestration while keeping submission guarded."""
    result = WorkflowModeRunner(repo).autopilot(competition_slug)
    _emit_mode_result(result.mode, result.mission, result.handoff_path)


@app.command("status")
def status(
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to inspect."),
    ] = Path("."),
) -> None:
    """Show current resumable runtime state."""
    current = RuntimeState(repo).current_status()
    events = EventBus(repo / ".kgmon").list_events(
        session_id=(
            str(current["session_id"])
            if isinstance(current.get("session_id"), str)
            else None
        )
    )
    typer.echo(f"state: {current['state_root']}")
    typer.echo(f"competition: {current['competition']}")
    typer.echo(f"mission: {current['mission']}")
    typer.echo(f"mode: {current['mode']}")
    typer.echo(f"artifacts: {current['artifacts']}")
    typer.echo(f"events: {len(events)}")
    hud = _read_json(repo / ".kgmon" / "hud" / "current.json")
    verification = hud.get("verification")
    if isinstance(verification, dict):
        typer.echo(
            "gates: "
            f"{verification.get('passed', 0)}/{verification.get('total', 0)} "
            f"passed"
        )


@app.command("replay")
def replay(
    session: Annotated[str, typer.Argument(help='Session id or "latest".')],
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to inspect."),
    ] = Path("."),
) -> None:
    """Replay a session timeline from structured event logs."""
    summary = SessionReplay(repo / ".kgmon").summarize(session)
    if summary.session_id is None:
        typer.echo("no replayable sessions found")
        raise typer.Exit(code=1)
    typer.echo(f"session: {summary.session_id}")
    typer.echo(f"command: {summary.command}")
    typer.echo(f"events: {summary.event_count}")
    for event_type in summary.event_types:
        typer.echo(f"- {event_type}")


@app.command("hud")
def hud(
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to inspect."),
    ] = Path("."),
) -> None:
    """Show the current OMC-style runtime HUD."""
    payload = _read_json(repo / ".kgmon" / "hud" / "current.json")
    if not payload:
        typer.echo("no HUD state found; run kgx setup first")
        raise typer.Exit(code=1)
    security = payload.get("security") if isinstance(payload, dict) else None
    verification = payload.get("verification") if isinstance(payload, dict) else None
    typer.echo(f"competition: {payload.get('active_competition')}")
    typer.echo(f"mission: {payload.get('active_mission')}")
    typer.echo(f"mode: {payload.get('active_mode')}")
    typer.echo(
        "security: "
        f"{security.get('mode') if isinstance(security, dict) else 'standard'}"
    )
    if isinstance(verification, dict):
        typer.echo(
            "verification: "
            f"{verification.get('passed', 0)}/{verification.get('total', 0)} "
            f"gates passed"
        )
        typer.echo(f"critical_failures: {verification.get('critical_failures', 0)}")


@mcp_app.command("install")
def mcp_install(
    client: Annotated[
        str,
        typer.Option("--client", help="Client: codex, claude, cursor, or vscode."),
    ],
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to configure."),
    ] = Path("."),
) -> None:
    """Install a stdio KGMON MCP config template for a local client."""
    _require_supported_mcp_client(client)
    RuntimeSetup(repo).setup_local()
    path = install_client_config(repo, client)
    typer.echo(f"{client} MCP config: {path}")
    typer.echo("command: python")
    typer.echo("args: -m kgmon_mcp.stdio")


@mcp_app.command("doctor")
def mcp_doctor(
    client: Annotated[
        str,
        typer.Option("--client", help="Client: codex, claude, cursor, or vscode."),
    ],
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to inspect."),
    ] = Path("."),
) -> None:
    """Validate the generated stdio KGMON MCP client config."""
    _require_supported_mcp_client(client)
    messages = doctor_client_config(repo, client)
    if messages:
        for message in messages:
            typer.echo(message)
        raise typer.Exit(code=1)
    typer.echo(f"{client} MCP config is healthy")


@skills_app.command("list")
def skills_list(
    domain: Annotated[
        str,
        typer.Option("--domain", help="Skill domain to list."),
    ] = "dsml",
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to inspect."),
    ] = Path("."),
) -> None:
    """List installed KGMON skills."""
    if domain != "dsml":
        typer.echo(f"unknown skill domain: {domain}")
        raise typer.Exit(code=1)
    RuntimeSetup(repo).setup_local()
    registry = load_skill_registry(repo / ".kgmon")
    groups = registry.get("groups")
    if isinstance(groups, dict):
        for group, skill_ids in groups.items():
            typer.echo(f"{group}:")
            if isinstance(skill_ids, list):
                for skill_id in skill_ids:
                    typer.echo(f"- {skill_id}")


@skills_app.command("inspect")
def skills_inspect(
    skill_id: Annotated[str, typer.Argument(help="DS/ML skill id.")],
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to inspect."),
    ] = Path("."),
) -> None:
    """Inspect an installed DS/ML skill."""
    RuntimeSetup(repo).setup_local()
    try:
        typer.echo(render_skill_inspection(repo / ".kgmon", skill_id))
    except KeyError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc


@prompt_app.command("run")
def prompt_run(
    prompt_id: Annotated[str, typer.Argument(help="DS/ML prompt id.")],
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to inspect."),
    ] = Path("."),
) -> None:
    """Render a DS/ML prompt and record it as a runtime artifact."""
    RuntimeSetup(repo).setup_local()
    try:
        content, artifact = run_prompt(repo / ".kgmon", prompt_id)
    except KeyError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(content)
    typer.echo(f"artifact: {artifact.relative_to(repo).as_posix()}")


@verify_app.command("all")
def verify_all(
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to verify."),
    ] = Path("."),
) -> None:
    """Run all deterministic verification gates and write fresh evidence."""
    report = VerificationEngine(repo).verify_all()
    typer.echo(
        f"verification: {report.passed}/{len(report.evidence)} gates passed"
    )
    typer.echo(f"critical_failures: {report.critical_failures}")
    typer.echo(f"evidence: {report.evidence_path}")
    for evidence in report.evidence:
        if evidence.status == "fail":
            typer.echo(f"{evidence.gate}: fail - {evidence.message}")
    if not report.ok:
        raise typer.Exit(code=1)


@package_app.command("final")
def package_final(
    workspace: Annotated[
        Path,
        typer.Option("--workspace", help="Competition workspace."),
    ] = Path("."),
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root for runtime state."),
    ] = Path("."),
) -> None:
    """Create a final reproducible package and emit package evidence."""
    RuntimeSetup(repo).setup_local()
    result = SubmissionPackager(workspace).package_final()
    bus = EventBus(repo / ".kgmon")
    session_id = bus.start_session(command="kgx package final")
    bus.emit(
        EventType.PACKAGE_CREATED,
        session_id=session_id,
        payload={"final_dir": str(result.final_dir)},
    )
    typer.echo(f"Final package: {result.final_dir}")


@app.command("submit")
def submit(
    final: Annotated[
        bool,
        typer.Option("--final", help="Submit artifacts/final/submission.csv."),
    ] = False,
    require_confirmation: Annotated[
        bool,
        typer.Option(
            "--require-confirmation",
            help="Require explicit confirmation before submitting.",
        ),
    ] = False,
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Explicitly confirm final submission."),
    ] = False,
    workspace: Annotated[
        Path,
        typer.Option("--workspace", help="Competition workspace."),
    ] = Path("."),
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root for runtime state."),
    ] = Path("."),
) -> None:
    """Submit final predictions through the guarded Kaggle submission bridge."""
    if not final:
        typer.echo("Pass --final to submit the packaged final submission.")
        raise typer.Exit(code=1)
    RuntimeSetup(repo).setup_local()
    policy = SecurityPolicy.for_repo(repo)
    try:
        result = SubmissionBridge(workspace, KaggleAccessAdapter()).submit_final(
            require_confirmation=require_confirmation,
            confirmed=confirm,
        )
    except RuntimeError as exc:
        policy.log(
            "submission_blocked",
            {
                "workspace": str(workspace),
                "require_confirmation": require_confirmation,
                "confirmed": confirm,
                "error": str(exc),
            },
        )
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    typer.echo(f"Submission status: {result.status}")


@doctor_app.callback(invoke_without_command=True)
def doctor(
    ctx: typer.Context,
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to inspect."),
    ] = Path("."),
) -> None:
    """Validate runtime setup."""
    if ctx.invoked_subcommand is not None:
        return
    _emit_report(RuntimeDoctor(repo).check())


@doctor_app.command("conflicts")
def doctor_conflicts(
    repo: Annotated[
        Path,
        typer.Option("--repo", help="Repository root to inspect."),
    ] = Path("."),
) -> None:
    """Detect conflicting runtime wiring."""
    _emit_report(RuntimeDoctor(repo).check_conflicts())


def _emit_report(report: RuntimeDoctorReport) -> None:
    for message in report.messages:
        typer.echo(message)
    if not report.ok:
        raise typer.Exit(code=1)


def _emit_mode_result(mode: str, mission: str, handoff_path: Path) -> None:
    typer.echo(f"mode: {mode}")
    typer.echo(f"mission: {mission}")
    typer.echo(f"handoffs: {handoff_path}")


app.add_typer(doctor_app, name="doctor")
app.add_typer(package_app, name="package")
app.add_typer(verify_app, name="verify")
app.add_typer(skills_app, name="skills")
app.add_typer(prompt_app, name="prompt")
app.add_typer(mcp_app, name="mcp")


def _read_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    import json

    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _require_supported_mcp_client(client: str) -> None:
    if client not in SUPPORTED_MCP_CLIENTS:
        typer.echo(f"unsupported MCP client: {client}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
