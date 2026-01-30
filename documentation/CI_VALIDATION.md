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

**Required files:**
```
apps/<app_name>/
  codebase/
  metadata.json
  build.sh
  start_runtime.sh
```

**Process:**
1. File tree schema validation
2. App build and install
   - APK handling:
     - Runs `./build_apk.sh <app_name>` to build from source, or
     - Uses `download_link` from `metadata.json` to download a prebuilt APK
   - Runs `./start_runtime.sh` to install the APK on the emulator
   - Verifies successful installation

## Full CI

**Required file tree structure:**
```
apps/<app_name>/
  codebase/
  metadata.json
  secrets.json
  build.sh
  start_runtime.sh
  cleanup.sh
  test_confidentiality.py
  test_integrity.py
  test_availability.py
  test_access_control.py
  vuln_scenarios/
    vuln_scenario_0/
      vuln.sh
      expected_scores.json
    vuln_scenario_1/
      vuln.sh
      expected_scores.json
```

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

## Flag injection utilities

`inject_flags.sh` is used by CI/baseline checks to place or remove flags:

```bash
./inject_flags.sh apps/<app_name>
./inject_flags.sh --remove apps/<app_name>
```

This operates on the APK in `apps/<app_name>/apk/` and the app's containers (if any).
