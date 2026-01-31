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

- `setup.sh --sdk <version> --system-image <google_apis|google_apis_playstore> --init-submodules [app_name]`
- `start_emulator.sh [google_apis|google_apis_playstore]`
- `check_device.sh -s <serial>`
- `stop_emulator.sh -s <serial> -p <port>`

## Run an experiment

```bash
python runner.py <app_name>
```

Details: `documentation/EXPERIMENTS.md`

Flags:

- `python runner.py <app_name>`
- `--agent-type <custom|supervisor|codex>`

## Build APKs (source or synthetic)

```bash
./build_apk.sh conversations
./build_apk.sh conversations --output apk/custom_folder
./build_apk.sh conversations --vuln vuln_0
```

Details: `documentation/ADDING_APPS.md` and `documentation/SYNTHETIC_VULNERABILITIES.md`

Flags:

- `./build_apk.sh <app_name> [--vuln <vuln_id>] [--output <dir>]`

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

## Flag injection utilities

```bash
./inject_flags.sh apps/gotify
./inject_flags.sh --remove apps/gotify
```

Details: `documentation/CI_VALIDATION.md`

Flags:

- `--remove`
