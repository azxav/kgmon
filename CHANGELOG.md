# Changelog

Development notes for the 0.1.0 tree. This file keeps the milestone history that used to live in the README.

## 0.1.0

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
- `kgx team --domain dsml` routing for strategy, EDA, validation, features, modeling, ablation, ensemble, postprocess, package, and verify
- Runtime guardrails for validation-first work, leakage audits, OOF evidence, external-data approval, provenance, and no automatic submission

Milestone 11 adds:

- Primary stdio MCP entrypoint via `python -m kgmon_mcp.stdio` and `kgmon-mcp`
- Cross-client underscore tool names such as `kgmon_doctor`, `kgmon_hud_get`, `kgmon_verify_all`, `kgmon_skills_list`, and `kgmon_prompt_run`
- Stable JSON-compatible result envelopes for public MCP tools
- Workspace discovery through `KGMON_HOME`, local `.kgmon/`, repository markers, or explicit `workspace_root`
- Lightweight `kgmon://...` resources and DS/ML prompt endpoints
- Client config helpers: `kgx mcp install --client <client>` and `kgx mcp doctor --client <client>`
- Stdio smoke, stdout contamination, schema compatibility, and tool contract tests
