# CI Validation

This document describes how CI validates apps and how to run equivalent checks locally.

## CI Modes
CI runs in two modes:
- **Simple CI**: Builds APK and verifies it can be installed on the emulator.
- **Full CI**: Runs all comprehensive tests including vulnerability scenarios.

The mode is determined by the presence of any of the four probe scripts in the app directory:
- `test_access_control.py`
- `test_availability.py`
- `test_confidentiality.py`
- `test_integrity.py`

If any of these exist, full CI runs; otherwise, simple CI runs.

## Simple CI

Requires: `codebase/`, `metadata.json`, `build.sh`, `start_runtime.sh`

**Process:**
1. File tree schema validation
2. App build and install
   - APK handling:
     - Runs `./build_apk.sh <app_name>` to build from source, or
     - Uses `download_link` from `metadata.json` to download a prebuilt APK
   - Runs `./start_runtime.sh` to install the APK on the emulator
   - Verifies successful installation

## Full CI

Requires all simple CI files plus: `secrets.json`, `cleanup.sh`, four probe scripts (`test_*.py`), and `vuln_scenarios/`. See `documentation/ADDING_APPS.md` for the complete file tree.

**Process:**
1. File tree schema validation
2. Baseline CIA check (no vulnerabilities)
   - `./start_runtime.sh`
   - `../../run_checks.sh .` → `scores.json`
   - Validate all numeric fields in `scores.json` are `1`
3. Vulnerable Scenario 0 (non‑DoS)
   - `./start_runtime.sh`
   - Run `vuln_scenarios/vuln_scenario_0/vuln.sh`
   - Run checks with injected log:
     - `../../run_checks.sh . vuln_scenarios/vuln_scenario_0/fake_agent_log.log`
   - Compare `scores.json` with `expected_scores.json`
4. Vulnerable Scenario 1 (DoS) — **optional**
   - Only runs if `metadata.json` has a non‑empty `app_server`
   - If no server, leave `app_server` empty and omit Scenario 1
   - If server exists:
     - `./start_runtime.sh`
     - Run `vuln_scenarios/vuln_scenario_1/vuln.sh`
     - `../../run_checks.sh .`
     - Compare `scores.json` with `expected_scores.json`

## CI Trigger and Local Testing

- CI runs on PR open and each push.
- To test locally, use:
```bash
./run_ci_local.sh apps/<app_name>
```

For flags:
```bash
./run_ci_local.sh --help
```

Notes:
- Ensure Docker is running.
- `--skip-apk` should not be used for simple CI (it defeats the APK build/fetch check).
- `cleanup.sh` should not remove the `.apk` file so `--skip-apk` can reuse it.

## Testing Synthetic Vulnerabilities

To test that a synthetic vulnerability's exploit and verification scripts work correctly:

```bash
./run_ci_local.sh apps/<app_name> --test-synthetic-vuln synthetic_vulnerabilities/vuln_0
```

This builds both regular and vulnerable APKs, runs the exploit, and verifies it succeeds on the vulnerable version but fails on the regular version.

### Using Prebuilt APKs

Use `--skip-apk` to skip building and use existing APKs:

```bash
./run_ci_local.sh apps/<app_name> --skip-apk --test-synthetic-vuln synthetic_vulnerabilities/vuln_0
```

**Behavior:**
1. Checks if both `apk/<app>.apk` and `apk/<vuln_id>/<app>.apk` exist locally
2. If missing, downloads from `download_link` in metadata.json
3. Fails if required APKs still don't exist after download

## Flag injection utilities

`inject_flags.sh` is used by CI/baseline checks to place or remove flags:

```bash
./inject_flags.sh apps/<app_name>
./inject_flags.sh --remove apps/<app_name>
```

This operates on the APK in `apps/<app_name>/apk/` and the app's containers (if any).
