# Running Experiments

This guide explains the standard experiment flow and what outputs to expect.

## Basic run

```bash
python runner.py <app_name>
```

Agent type defaults to `custom`; override with `--agent-type supervisor` or `--agent-type codex`.

The runner will:

1. Build or download the APK.
2. Start the emulator and install the app.
3. Run baseline probes (`run_checks.sh`).
4. Run the agent (if enabled, default custom agent unless overriden).
5. Run post-agent probes.
6. If `exploit.sh` exists, reset and execute the exploit, then re-run probes.

## Dry-run mode (no model calls)

```bash
python runner.py <app_name> runner_config_dryrun.json
```

This starts the full environment and gives you a Kali shell for manual testing.

## Runner config files (what to edit)

The default config is `runner_config.json`. For dry-run use `runner_config_dryrun.json`.

Key fields to know:

- `model`: Model name (drives provider selection).
- `dry_run`: If true, no API calls are made and you get an interactive shell.
- `max_iterations`: How many agent iterations to run.
- `adb_access`, `server_access`, `docker_mode`: Control agent access and runtime mode.
- `allowed_tools`: Tool allowlist for the agent.

Agent type is selected via the CLI (`--agent-type`) rather than the config file.

If you are not using API keys, prefer `runner_config_dryrun.json`.

## Synthetic vulnerability runs

Use this when you want to test a synthetic patch + exploit workflow.

Build regular and vulnerable APKs:

```bash
./build_apk.sh <app_name>
./build_apk.sh <app_name> --vuln vuln_0
```

Run the synthetic CI test locally:

```bash
APP_NAME=<app_name>
./run_ci_local.sh apps/$APP_NAME --test-synthetic-vuln synthetic_vulnerabilities/vuln_0
```

If APKs already exist, skip rebuilding:

```bash
./run_ci_local.sh apps/$APP_NAME --skip-apk --test-synthetic-vuln synthetic_vulnerabilities/vuln_0
```

For full details (file structure, verify scripts, publish bundles), see `documentation/SYNTHETIC_VULNERABILITIES.md`.

## Build modes (source vs download)

Apps can provide APKs in two ways:

- **Source build** via `setup_app_source.sh` (preferred)
- **Download** via `metadata.json:download_link`

Local CI automatically selects modes based on which setup scripts exist:

```bash
./run_ci_local.sh apps/<app_name>                 # run all available modes
./run_ci_local.sh apps/<app_name> --skip-build    # download-only
./run_ci_local.sh apps/<app_name> --skip-download # source-only
./run_ci_local.sh apps/<app_name> --skip-apk      # reuse existing APKs
```

## Common outputs

- `scores.json`: probe results for baseline or post-agent checks.
- `generic_scores.json`: generic probe outputs.
- `exploit_log_*.log`: exploit execution logs (if exploit is generated).
- Timing reports `timings_*.json` (agent performance data).

## CI-equivalent local test

```bash
./run_ci_local.sh apps/<app_name>
```

This simulates CI and validates file structure, builds, installs, and probes.

## Runner config

See `runner_config.json` and `runner_config_dryrun.json` for examples. The keys above are the ones most people edit.
