# Command Quick Reference

This is a cheat sheet. For details and examples, follow the linked docs.

## Setup and emulator

```bash
bash setup.sh --init-submodules conversations
./start_emulator.sh
./check_device.sh
./stop_emulator.sh
```

Details: `documentation/GETTING_STARTED.md`

Flags:

- `setup.sh [app_name] --init-submodules [app_name]`
- `start_emulator.sh <33|34|35>`
- `check_device.sh -s <serial>`
- `stop_emulator.sh -s <serial> -p <port>`

## Run an experiment

```bash
python runner.py <app_name>
```

Details: `documentation/EXPERIMENTS.md`

Flags:

- `python runner.py <app_name>` — run the workflow declared in `runner_config.json` against `<app_name>`.
- `--config <path>` — use an alternate runner config file (default: `runner_config.json`).
- `--explain-config` — print the JSON Schema for `runner_config.json` (field names, types, defaults, descriptions) and exit. Same content as `schemas/runner_config.schema.json`.

Agent implementation (`custom` in-process Python loop, or `external` BYO Docker image) is selected via the `agent_mode` field in `runner_config.json`. See `documentation/EXPERIMENTS.md#agent-mode` and `documentation/BRING_YOUR_OWN_AGENT.md`.

## Download pre-built APKs

```bash
python download_apk.py conversations
python download_apk.py --force conversations
python download_apk.py --check
```

Details: `documentation/ADDING_APPS.md`

Flags:

- `python download_apk.py <app_name>` — download APK (skips existing files)
- `--force` — overwrite existing files
- `--check [app_name]` — validate `download_links` against GitHub releases

## Build and publish APKs

```bash
./build_apk.sh conversations
./build_apk.sh conversations --vuln vuln_0
./build_apk.sh home-assistant-android --hardened-patch /path/to/fix.patch
./publish_apk_bundle.sh apps/conversations
```

Details: `documentation/ADDING_APPS.md`, `documentation/SYNTHETIC_VULNERABILITIES.md`, and `documentation/ZERODAY_TASKS.md`

Flags:

- `./build_apk.sh <app_name> [--vuln <vuln_id>] [--output <dir>]`
- `./build_apk.sh <app_name> --hardened` (uses `security.patch` from `zerodays` submodule)
- `./build_apk.sh <app_name> --hardened-patch <patch_path>` (uses explicit patch file; for zero-day tasks, point it at `apps/<app>/zero_day_vulnerabilities/<task_id>/fix.patch` or `reports/<app>/<report>/task/fix.patch`)
- `./publish_apk_bundle.sh apps/<app_name>`

Note: `--vuln`, `--hardened`, and `--hardened-patch` are mutually exclusive.

## Local CI validation

```bash
./run_ci_local.sh apps/conversations
```

Details: `documentation/CI_VALIDATION.md`

Flags:

- `--skip-build`
- `--skip-download`
- `--skip-apk`
- `--unit-tests`
- `--test-synthetic-vuln <vuln_dir>`
- `--test-zero-day-vuln <task_dir>`

## Zero-day task validation

```bash
./scripts/validate_task_bundle.sh \
  --app app-name \
  --task-dir /path/to/task
```

Details: `documentation/CI_VALIDATION.md` and `documentation/ZERODAY_TASKS.md`

## External zero-day report wrapper

```bash
./scripts/validate_zero_day_report.sh \
  --app app-name \
  --report-dir /path/to/reports/app-name/report-n
```

Details: `documentation/CI_VALIDATION.md` and `documentation/ZERODAY_TASKS.md`

## Flag injection utilities

```bash
./inject_flags.sh apps/gotify
./inject_flags.sh --remove apps/gotify
```

Details: `documentation/CI_VALIDATION.md`

Flags:

- `--remove`
