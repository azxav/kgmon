# KGMON Codex Plugin and MCP Setup Guide

This guide shows how to install this repository for local Codex use and wire its
stdio MCP server into Codex.

KGMON-Codex works as a local Codex plugin backed by a Python package and a
stdio MCP server. The plugin manifest lives at `.codex-plugin/plugin.json`, and
Codex loads its MCP server from `.mcp.json` through `kgmon_mcp.stdio`.

## Prerequisites

- Python 3.11 or newer
- Git
- Codex Desktop or Codex CLI with MCP support
- Kaggle credentials, if you want Kaggle downloads, notebooks, or submissions

For Kaggle credentials, prefer a single token:

```powershell
$env:KAGGLE_API_TOKEN = "<your-token>"
```

Legacy credentials are also supported:

```powershell
$env:KAGGLE_USERNAME = "<your-username>"
$env:KAGGLE_KEY = "<your-key>"
```

`.env.example` lists the same variable names. kgmon reads the process
environment; export the values in the shell that starts the CLI or MCP server.

## 1. Get the Repo Ready

From the repository root:

```powershell
git submodule update --init --recursive
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

If you do not need development tools, use:

```powershell
python -m pip install -e .
```

The editable install exposes these commands:

- `kgx`, the Codex-oriented runtime launcher
- `kgmon`, the Kaggle automation CLI
- `kgmon-mcp`, the MCP server entrypoint

## 2. Initialize KGMON Runtime State

Run:

```powershell
kgx setup --local
```

This creates or refreshes:

- `.kgmon/`, the local runtime state directory
- `.mcp.json`, the project MCP config
- `.kgmon/runtime-config.json`
- `.kgmon/hud/current.json`
- `.kgmon/logs/*.jsonl`

If the repo already has state files and you want to repair managed files, run:

```powershell
kgx setup --repair
```

## 3. Install the MCP Config for Codex

Run:

```powershell
kgx mcp install --client codex
kgx mcp doctor --client codex
```

The generated `.mcp.json` should look like this. `KGMON_HOME` is the absolute
path of this repository on your machine:

```json
{
  "mcpServers": {
    "kgmon": {
      "command": "python",
      "args": ["-m", "kgmon_mcp.stdio"],
      "env": {
        "KGMON_HOME": "/absolute/path/to/kgmon",
        "KGMON_SECURITY": "strict"
      },
      "x-kgmon-managed": true
    }
  }
}
```

After changing `.mcp.json`, restart Codex or reload the workspace so Codex can
discover the `kgmon` MCP server.

To make it visible as a local Codex plugin in the app, add this repository to a
local marketplace entry that points to a plugin folder or junction named
`kgmon`. The plugin manifest name is `kgmon`, and the app display name is
`KGMON-Codex`.

A local Codex marketplace can point at a plugin folder that contains this
repo's `.codex-plugin/plugin.json` and `.mcp.json`:

```text
<marketplace-root>/.agents/plugins/marketplace.json
<marketplace-root>/plugins/kgmon/.codex-plugin/plugin.json
<marketplace-root>/plugins/kgmon/.mcp.json
```

Then install it through Codex:

```powershell
codex plugin marketplace add <marketplace-root>
codex plugin add kgmon@personal
codex plugin list
codex mcp list
```

If `codex plugin list` says the personal marketplace JSON is invalid at line 1
column 1, rewrite `marketplace.json` as UTF-8 without BOM.

## 4. Verify Codex Can Use the Server

First verify from the terminal:

```powershell
kgx mcp doctor --client codex
python -m kgx_cli.main mcp doctor --client codex
python -m kgmon_mcp.stdio
```

The `python -m kgmon_mcp.stdio` command starts the stdio server and waits for MCP
messages. Stop it with `Ctrl+C`; Codex starts it automatically when configured.

Then ask Codex to use KGMON, for example:

```text
Use the kgmon MCP server to run kgmon_doctor.
```

Useful public MCP tools include:

- `kgmon_doctor`
- `kgmon_kaggle_doctor`
- `kgmon_skills_list`
- `kgmon_prompts_list`
- `kgmon_prompt_run`
- `kgmon_bootstrap_competition`
- `kgmon_data_profile`
- `kgmon_validation_plan`
- `kgmon_experiment_plan`
- `kgmon_experiment_run`
- `kgmon_ensemble_search`
- `kgmon_package_final`
- `kgmon_verify_all`
- `kgmon_hud_get`
- `kgmon_status_get`

Useful MCP resources include:

- `kgmon://state/current`
- `kgmon://mission/current`
- `kgmon://hud/current`
- `kgmon://competition/current/manifest`
- `kgmon://competition/current/profile`
- `kgmon://competition/current/validation`
- `kgmon://competition/current/artifacts`
- `kgmon://competition/current/final-package`
- `kgmon://logs/events`

## 5. Optional: Configure Other MCP Clients

The same helper supports several local clients:

```powershell
kgx mcp install --client claude
kgx mcp install --client cursor
kgx mcp install --client vscode
```

For VS Code, the config is written to:

```text
.vscode/mcp.json
```

For Codex, Claude, and Cursor, the config is written to:

```text
.mcp.json
```

## 6. Common Workflows

Check runtime health:

```powershell
kgx doctor
kgx doctor conflicts
```

List KGMON DS/ML skills:

```powershell
kgx skills list --domain dsml
kgx skills inspect kgmon-validation-leakage-auditor
```

Run a prompt pack:

```powershell
kgx prompt run validation-design
kgx prompt run ensemble-search
```

Start a Kaggle mission:

```powershell
kgx deep-interview titanic
kgx ralplan titanic
kgx team --domain dsml
```

Run the guarded final package flow:

```powershell
kgx verify all
kgx package final --workspace competitions/titanic
kgx submit --final --require-confirmation --confirm --workspace competitions/titanic
```

## Troubleshooting

If Codex does not show the KGMON tools, check these in order:

1. Confirm the package is installed in the Python environment Codex will use:

   ```powershell
   python -c "import kgmon_mcp; print(kgmon_mcp.__file__)"
   ```

2. Confirm `.mcp.json` exists and has an absolute `KGMON_HOME` path:

   ```powershell
   Get-Content .mcp.json
   ```

3. Validate the generated Codex MCP config:

   ```powershell
   kgx mcp doctor --client codex
   ```

4. Repair managed runtime files if local state is stale:

   ```powershell
   kgx setup --repair
   ```

5. Restart Codex after changing `.mcp.json`.

If `kgx doctor` reports an invalid runtime schema, run `kgx setup --repair` and
then re-run `kgx doctor`.

If Kaggle commands fail, run:

```powershell
kgmon kaggle doctor
```

From Codex, ask it to call the `kgmon_kaggle_doctor` MCP tool through the
configured server.
