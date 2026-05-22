from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from kgmon_core.bootstrap import CompetitionBootstrapper
from kgmon_core.ensembles import EnsembleEngine
from kgmon_core.experiments import (
    BaselineExperimentPlanner,
    BaselineExperimentRunner,
    ExperimentDagRunner,
)
from kgmon_core.kaggle_bridge import KaggleNotebookBridge, SubmissionBridge
from kgmon_core.packaging import SubmissionPackager
from kgmon_core.profiling import CompetitionProfiler
from kgmon_core.registry import ArtifactRegistry
from kgmon_core.rules import RuleMetricParser
from kgmon_core.validation import ValidationPlanner
from kgmon_kaggle.adapter import KaggleAccessAdapter
from kgmon_kaggle.doctor import build_doctor_report

app = typer.Typer(help="KGMON-Codex Kaggle automation tools.")
kaggle_app = typer.Typer(help="Kaggle access diagnostics and operations.")
competition_app = typer.Typer(help="Competition workspace operations.")
data_app = typer.Typer(help="Competition data profiling operations.")
validation_app = typer.Typer(help="Validation planning operations.")
experiment_app = typer.Typer(help="Baseline experiment planning and execution.")
artifacts_app = typer.Typer(help="Artifact registry operations.")
ensemble_app = typer.Typer(help="Ensemble search operations.")
package_app = typer.Typer(help="Final package operations.")
notebook_app = typer.Typer(help="Kaggle notebook bridge operations.")

DEFAULT_DOCTOR_MODULES = ("kagglehub", "kaggle", "python-dotenv", "requests")
VENDOR_PATH = Path(__file__).resolve().parents[1] / "vendor" / "kaggle-skill"


@app.callback()
def main() -> None:
    """Run KGMON commands."""


@kaggle_app.command("doctor")
def kaggle_doctor() -> None:
    """Report dependency and Kaggle credential status without leaking secrets."""
    report = build_doctor_report(
        DEFAULT_DOCTOR_MODULES,
        sys.version_info,
        vendor_available=VENDOR_PATH.exists(),
    )
    typer.echo(report.to_text())
    if not all(check.installed for check in report.dependencies):
        raise typer.Exit(code=1)


@competition_app.command("bootstrap")
def competition_bootstrap(
    slug: str,
    workspace_root: Annotated[
        Path,
        typer.Option(
            "--workspace-root",
            help="Directory where competitions/<slug> will be created.",
        ),
    ] = Path("."),
) -> None:
    """Create the M2 competition workspace from Kaggle metadata and data."""
    result = CompetitionBootstrapper(
        adapter=KaggleAccessAdapter(),
        workspace_root=workspace_root,
    ).bootstrap(slug)
    typer.echo(f"Bootstrapped {result.slug}: {result.workspace}")
    typer.echo(f"- pages: {result.page_count}")
    typer.echo(f"- downloaded files: {result.downloaded_files}")
    typer.echo(f"- config: {result.config_path}")
    typer.echo(f"- registry: {result.registry_path}")


@competition_app.command("audit-rules")
def competition_audit_rules(
    workspace: Annotated[
        Path,
        typer.Option(
            "--workspace",
            help="Competition workspace containing Kaggle page captures.",
        ),
    ] = Path("."),
) -> None:
    """Parse Kaggle rules/evaluation pages into competition.yaml."""
    result = RuleMetricParser(workspace).parse_and_update_config()
    typer.echo(f"Rules audited: {workspace / 'configs' / 'competition.yaml'}")
    typer.echo(f"- metric: {result.metric_name}")
    typer.echo(f"- direction: {result.metric_direction}")
    typer.echo(f"- external_data: {result.external_data}")
    typer.echo(f"- internet_allowed: {result.internet_allowed}")
    typer.echo(f"- human_review_required: {result.human_review_required}")


@data_app.command("profile")
def data_profile(
    workspace: Annotated[
        Path,
        typer.Option(
            "--workspace",
            help="Competition workspace containing configs/competition.yaml.",
        ),
    ] = Path("."),
) -> None:
    """Generate the M3 data profile JSON and Markdown report."""
    result = CompetitionProfiler(workspace).profile()
    typer.echo(f"Profile written: {result.profile_path}")
    typer.echo(f"Report written: {result.report_path}")
    typer.echo(f"- task_family: {result.task_family}")
    typer.echo(f"- target_column: {result.target_column}")
    typer.echo(f"- id_column: {result.id_column}")


@validation_app.command("plan")
def validation_plan(
    workspace: Annotated[
        Path,
        typer.Option(
            "--workspace",
            help="Competition workspace containing profile and competition config.",
        ),
    ] = Path("."),
) -> None:
    """Create fold assignments, validation.yaml, and leakage guard status."""
    result = ValidationPlanner(workspace).plan()
    typer.echo(f"Validation plan written: {result.validation_path}")
    typer.echo(f"Folds written: {result.folds_path}")
    typer.echo(f"- strategy: {result.strategy}")
    if result.leakage_blocked:
        typer.echo("Validation blocked by leakage guards:")
        for warning in result.leakage_warnings:
            typer.echo(f"- {warning}")
        raise typer.Exit(code=1)
    typer.echo("Validation ready.")


@experiment_app.command("plan")
def experiment_plan(
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="Experiment plan mode.",
        ),
    ] = "baseline",
    workspace: Annotated[
        Path,
        typer.Option(
            "--workspace",
            help="Competition workspace containing configs/competition.yaml.",
        ),
    ] = Path("."),
) -> None:
    """Create immutable baseline experiment specs."""
    result = BaselineExperimentPlanner(workspace).plan(mode=mode)
    typer.echo(f"Experiment plan written: {result.experiments_path}")
    for spec_path in result.spec_paths:
        typer.echo(f"- baseline-sklearn-dummy: {spec_path}")


@experiment_app.command("run")
def experiment_run(
    run_all: Annotated[
        bool,
        typer.Option(
            "--all",
            help="Run all planned baseline experiments.",
        ),
    ] = False,
    dag: Annotated[
        Path | None,
        typer.Option(
            "--dag",
            help="Experiment DAG YAML to execute.",
        ),
    ] = None,
    workspace: Annotated[
        Path,
        typer.Option(
            "--workspace",
            help="Competition workspace containing planned experiments.",
        ),
    ] = Path("."),
) -> None:
    """Execute planned experiments and write prediction contracts."""
    if dag is not None:
        dag_result = ExperimentDagRunner(workspace).run(dag)
        if dag_result.completed:
            typer.echo(f"DAG completed: {', '.join(dag_result.completed)}")
        if dag_result.failed:
            typer.echo(f"DAG failed: {', '.join(dag_result.failed)}")
            raise typer.Exit(code=1)
        return

    if not run_all:
        typer.echo("Pass --all or --dag to run planned experiments.")
        raise typer.Exit(code=1)
    run_result = BaselineExperimentRunner(workspace).run_all()
    typer.echo(f"Experiment completed: {run_result.run_id}")
    typer.echo(f"- {run_result.metric_name}: {run_result.metric_value:.6f}")
    typer.echo(f"- OOF predictions: {run_result.oof_path}")
    typer.echo(f"- test predictions: {run_result.test_predictions_path}")
    typer.echo(f"- model artifact: {run_result.model_path}")


@artifacts_app.command("list")
def artifacts_list(
    workspace: Annotated[
        Path,
        typer.Option(
            "--workspace",
            help="Competition workspace containing artifacts/registry.sqlite.",
        ),
    ] = Path("."),
) -> None:
    """List registered artifacts with run lineage."""
    artifacts = ArtifactRegistry(workspace).list_artifacts()
    for artifact in artifacts:
        run_id = artifact.run_id or "-"
        typer.echo(f"{run_id}\t{artifact.type}\t{artifact.path}")


@ensemble_app.command("search")
def ensemble_search(
    workspace: Annotated[
        Path,
        typer.Option(
            "--workspace",
            help="Competition workspace containing prediction artifacts.",
        ),
    ] = Path("."),
) -> None:
    """Search simple ensemble candidates and write ensemble submission."""
    result = EnsembleEngine(workspace).search()
    typer.echo(f"Ensemble config: {result.config_path}")
    typer.echo(f"Submission: {result.submission_path}")


@package_app.command("final")
def package_final(
    workspace: Annotated[
        Path,
        typer.Option(
            "--workspace",
            help="Competition workspace containing ensemble outputs.",
        ),
    ] = Path("."),
) -> None:
    """Create the final reproducible submission package."""
    result = SubmissionPackager(workspace).package_final()
    typer.echo(f"Final package: {result.final_dir}")


@notebook_app.command("push")
def notebook_push(
    final: Annotated[
        bool,
        typer.Option("--final", help="Push artifacts/final/solution.ipynb."),
    ] = False,
    workspace: Annotated[
        Path,
        typer.Option("--workspace", help="Competition workspace."),
    ] = Path("."),
) -> None:
    """Push the final notebook through the Kaggle adapter."""
    if not final:
        typer.echo("Pass --final to push the packaged solution notebook.")
        raise typer.Exit(code=1)
    result = KaggleNotebookBridge(workspace, KaggleAccessAdapter()).push_final()
    typer.echo(f"Notebook pushed: {result.notebook_ref}")


@notebook_app.command("run")
def notebook_run(
    notebook_ref: Annotated[
        str | None,
        typer.Option("--notebook-ref", help="Kaggle notebook reference."),
    ] = None,
    final: Annotated[
        bool,
        typer.Option("--final", help="Run the last pushed final notebook."),
    ] = False,
    workspace: Annotated[
        Path,
        typer.Option("--workspace", help="Competition workspace."),
    ] = Path("."),
) -> None:
    """Run or inspect the final Kaggle notebook through the adapter."""
    if not final:
        typer.echo("Pass --final to run the final solution notebook.")
        raise typer.Exit(code=1)
    ref = notebook_ref or _read_notebook_ref(workspace)
    result = KaggleNotebookBridge(workspace, KaggleAccessAdapter()).run_final(ref)
    typer.echo(f"Notebook job: {result.job_id}")


@notebook_app.command("fetch-output")
def notebook_fetch_output(
    notebook_ref: Annotated[
        str | None,
        typer.Option("--notebook-ref", help="Kaggle notebook reference."),
    ] = None,
    final: Annotated[
        bool,
        typer.Option("--final", help="Fetch output from the final notebook."),
    ] = False,
    workspace: Annotated[
        Path,
        typer.Option("--workspace", help="Competition workspace."),
    ] = Path("."),
) -> None:
    """Fetch final Kaggle notebook outputs through the adapter."""
    if not final:
        typer.echo("Pass --final to fetch final notebook outputs.")
        raise typer.Exit(code=1)
    ref = notebook_ref or _read_notebook_ref(workspace)
    result = KaggleNotebookBridge(workspace, KaggleAccessAdapter()).fetch_output(ref)
    typer.echo(f"Notebook output: {result.output_path}")


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
) -> None:
    """Submit final predictions through the guarded Kaggle submission bridge."""
    if not final:
        typer.echo("Pass --final to submit the packaged final submission.")
        raise typer.Exit(code=1)
    result = SubmissionBridge(workspace, KaggleAccessAdapter()).submit_final(
        require_confirmation=require_confirmation,
        confirmed=confirm,
    )
    typer.echo(f"Submission status: {result.status}")


def _read_notebook_ref(workspace: Path) -> str:
    path = workspace / "kaggle" / "notebooks" / "push_response.json"
    if not path.exists():
        raise typer.BadParameter("notebook ref is required before push response exists")
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    return str(payload["notebook_ref"])


app.add_typer(kaggle_app, name="kaggle")
app.add_typer(competition_app, name="competition")
app.add_typer(data_app, name="data")
app.add_typer(validation_app, name="validation")
app.add_typer(experiment_app, name="experiment")
app.add_typer(artifacts_app, name="artifacts")
app.add_typer(ensemble_app, name="ensemble")
app.add_typer(package_app, name="package")
app.add_typer(notebook_app, name="notebook")
