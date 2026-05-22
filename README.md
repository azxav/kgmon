# KGMON-Codex Kaggle Automation Plugin

KGMON-Codex is a Codex-compatible Kaggle competition automation plugin. It wraps
`shepsci/kaggle-skill` for Kaggle platform access and adds the KGMON software
spine for workspace management, contracts, experiments, governance, and final
solution packaging.

Milestone 1 provides:

- Python package skeleton
- Typer CLI entrypoint
- MCP server entrypoint stub
- Kaggle dependency and credential diagnostics
- Secret redaction utilities
- `vendor/kaggle-skill` integration point

Milestone 2 adds:

- `KaggleAccessAdapter` wrapping vendored Kaggle skill scripts and Kaggle CLI
- Competition workspace generation under `competitions/<slug>/`
- Kaggle page capture with untrusted-content wrappers
- `configs/competition.yaml` generation
- SQLite artifact registry for raw competition files

Milestone 3 adds:

- Rules and metric parsing from captured Kaggle pages
- Data profiling with schema, missing-value, duplicate, target, and drift reports
- `configs/competition.yaml` enrichment for inferred task, target, ID, metric, and rules
- Validation planning with persisted folds in `data/processed/folds.csv`
- Leakage guard reporting that blocks validation when high-risk signals are detected

Milestone 4 adds:

- Baseline experiment specs under `configs/model_params/`
- A sklearn-style dummy baseline trainer interface and execution path
- Optional LightGBM, XGBoost, and CatBoost adapter placeholders with clear dependency errors
- OOF prediction contracts in `artifacts/oof/`
- Test prediction contracts in `artifacts/test_preds/`
- Baseline model artifacts and run reports

Milestone 5 adds:

- Experiment DAG execution with dependency ordering and retry metadata
- SQLite run lineage for models, predictions, reports, ensembles, submissions, and final packages
- Local MLflow-compatible tracking output under `mlruns/`
- Ensemble search with weighted averaging, greedy hill climbing, rank averaging, and stacking report metadata
- Final package generation under `artifacts/final/`
- Kaggle notebook push/run/output and guarded submission bridge
- Codex-facing MCP resources and tool wrappers with secret redaction

Milestone 6 adds:

- `kgx` as the final user-facing OMC-style runtime launcher
- Local `.kgmon/` state root creation with state, mission, HUD, hook, and log directories
- Runtime config, project memory, notepad, security policy, and log file initialization
- Deterministic `.mcp.json` generation and repair while preserving existing MCP servers
- `kgx doctor` and `kgx doctor conflicts` runtime health checks
- KGMON MCP runtime resources and initial tool stubs

Milestone 8 adds:

- `kgmon_agents` software-role registry for build/ML, review, domain, and coordination lanes
- Explicit permitted tools, artifact contracts, and verification obligations per role
- Bounded worker handoffs that store descriptors instead of large inline payloads
- `kgx deep-interview`, `kgx ralplan`, `kgx team`, `kgx ralph`, `kgx ultrawork`, and `kgx autopilot`
- Resumable mode history, active mode, HUD, team assignment, safe limits, and guarded submission state

Milestone 9 adds:

- Deterministic verification gate registry with fresh evidence under `.kgmon/missions/<mission>/verification.json`
- `KGMON_SECURITY=strict` runtime policy with path allowlisting, security logs, external-data checks, and guarded submissions
- `kgx verify all`, `kgx hud`, `kgx status`, and enriched `kgx replay latest`
- `kgx package final` and `kgx submit --final --require-confirmation` runtime commands
- MCP `kgmon.verify.all`, `kgmon.hud.get`, `kgmon.replay.session`, and guarded submit/package stubs

Milestone 10 adds:

- DS/ML-only skill, prompt, checklist, and agent-contract packs under `.kgmon/`
- `kgx skills list --domain dsml` and `kgx skills inspect <skill-id>`
- `kgx prompt run <prompt-id>` with prompt-run artifacts
- `kgx team --domain dsml` routing for strategy -> EDA -> validation -> features -> modeling -> ablation -> ensemble -> postprocess -> package -> verify
- Runtime guardrails for validation-first work, leakage audits, OOF evidence, external-data approval, provenance, and no automatic submission

Milestone 11 adds:

- Primary stdio MCP entrypoint via `python -m kgmon_mcp.stdio` and `kgmon-mcp`
- Cross-client underscore tool names such as `kgmon_doctor`, `kgmon_hud_get`, `kgmon_verify_all`, `kgmon_skills_list`, and `kgmon_prompt_run`
- Stable JSON-compatible result envelopes for public MCP tools
- Workspace discovery through `KGMON_HOME`, local `.kgmon/`, repository markers, or explicit `workspace_root`
- Lightweight `kgmon://...` resources and DS/ML prompt endpoints
- Client config helpers: `kgx mcp install --client <client>` and `kgx mcp doctor --client <client>`
- Stdio smoke, stdout contamination, schema compatibility, and tool contract tests

## CLI

```bash
kgx setup --local
kgx setup --repair
kgx doctor
kgx doctor conflicts
kgx deep-interview titanic
kgx ralplan titanic
kgx team 4:modeler "build baseline and ensemble"
kgx team --domain dsml
kgx skills list --domain dsml
kgx skills inspect kgmon-validation-leakage-auditor
kgx prompt run validation-design
kgx prompt run ensemble-search
kgx mcp install --client codex
kgx mcp doctor --client codex
kgx ralph "verify and package final solution"
kgx ultrawork "expand model lanes"
kgx autopilot titanic
KGMON_SECURITY=strict kgx doctor
kgx verify all
kgx hud
kgx replay latest
kgx package final --workspace competitions/titanic
kgx submit --final --require-confirmation --workspace competitions/titanic
python -m kgmon_mcp.stdio
kgmon-mcp

kgmon --help
kgmon kaggle doctor
kgmon competition bootstrap titanic
kgmon competition audit-rules --workspace competitions/titanic
kgmon data profile --workspace competitions/titanic
kgmon validation plan --workspace competitions/titanic
kgmon experiment plan --mode baseline --workspace competitions/titanic
kgmon experiment run --all --workspace competitions/titanic
kgmon experiment run --dag competitions/titanic/configs/experiments/baseline_dag.yaml --workspace competitions/titanic
kgmon artifacts list --workspace competitions/titanic
kgmon ensemble search --workspace competitions/titanic
kgmon package final --workspace competitions/titanic
kgmon notebook push --final --workspace competitions/titanic
kgmon notebook run --final --workspace competitions/titanic
kgmon notebook fetch-output --final --workspace competitions/titanic
kgmon submit --final --require-confirmation --confirm --workspace competitions/titanic
```

`kgmon kaggle doctor` checks Python, Kaggle-related dependencies, the vendored
Kaggle skill directory, and Kaggle credential availability without printing raw
secret values.

`kgmon competition bootstrap <slug>` creates the planned M2 workspace, downloads
competition files into `data/raw`, saves Kaggle pages in `kaggle/pages`, writes
`configs/competition.yaml`, and registers raw files in
`artifacts/registry.sqlite`.

`kgmon competition audit-rules --workspace <workspace>` parses the captured
Kaggle rules and evaluation pages, then updates `configs/competition.yaml` with
known rule fields and metric direction.

`kgmon data profile --workspace <workspace>` inspects train, test, and sample
submission CSV files, writes `artifacts/reports/profile.json` and
`artifacts/reports/profile.md`, and updates the competition config with inferred
data contract fields.

`kgmon validation plan --workspace <workspace>` chooses an initial validation
strategy, writes fold assignments, persists `configs/validation.yaml`, and exits
non-zero when leakage guards block experiments.

`kgmon experiment plan --mode baseline --workspace <workspace>` writes the M4
baseline experiment plan and immutable sklearn baseline spec.

`kgmon experiment run --all --workspace <workspace>` executes the planned
baseline, writes OOF and test prediction CSVs using the M4 contracts, stores the
baseline model artifact, and records a JSON run report.

`kgmon experiment run --dag <path> --workspace <workspace>` executes DAG nodes in
dependency order and registers lineage in `artifacts/registry.sqlite`.

`kgmon artifacts list --workspace <workspace>` prints registered artifacts with
their producing run IDs.

`kgmon ensemble search --workspace <workspace>` builds
`artifacts/ensembles/ensemble_v001.yaml` and
`artifacts/submissions/submission_ensemble_v001.csv`.

`kgmon package final --workspace <workspace>` validates the ensemble submission
and creates the final reproducible package, including `submission.csv`,
`inference.py`, `solution.ipynb`, environment files, provenance, and report.

Notebook and submission commands call the Kaggle adapter layer and archive their
responses under `kaggle/notebooks/` and `kaggle/submissions/`. Final submission
is guarded and requires explicit confirmation unless competition rules allow
automatic submission.
