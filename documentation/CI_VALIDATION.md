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

`run_checks.sh` writes runtime score files separately: app-specific scores to `scores.json`, generic scores to `generic_scores.json`, and remote-attacker scores to `scores_remote_attacker.json` when enabled.

**Process:**
1. File tree schema validation
2. Baseline CIA check (no vulnerabilities)
   - `./start_runtime.sh`
   - `../../run_checks.sh .` → `scores.json` and `generic_scores.json`
   - Validate all numeric fields in `scores.json` and `generic_scores.json` are `1`
   - If remote-attacker probes are enabled and produce `scores_remote_attacker.json`, validate its top-level scores are `1`
3. Vulnerable Scenario 0 (non‑DoS)
   - `./start_runtime.sh`
   - Run `vuln_scenarios/vuln_scenario_0/vuln.sh`
   - Run checks with injected log:
     - `../../run_checks.sh . vuln_scenarios/vuln_scenario_0/fake_agent_log.log`
   - Compare runtime `scores.json` with reference `expected_scores.json`
   - Generic runtime output remains separate in `generic_scores.json`; these scenario steps compare app-specific scores
   - If remote-attacker probes are enabled and reference `expected_scores_remote_attacker.json` is present, compare it with runtime `scores_remote_attacker.json`
4. Vulnerable Scenario 1 (DoS) — **optional**
   - Only runs if `metadata.json` has a non‑empty `app_server`
   - If no server, leave `app_server` empty and omit Scenario 1
   - If server exists:
     - `./start_runtime.sh`
     - Run `vuln_scenarios/vuln_scenario_1/vuln.sh`
     - `../../run_checks.sh .`
     - Compare runtime `scores.json` with reference `expected_scores.json`
     - Generic runtime output remains separate in `generic_scores.json`; these scenario steps compare app-specific scores
     - If remote-attacker probes are enabled and reference `expected_scores_remote_attacker.json` is present, compare it with runtime `scores_remote_attacker.json`

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
- For apps that opt into `apk_obfuscation`, CI also emits an obfuscated `handle_apk` job (build-only validation) on every change that triggers a rebuild. The heavier obfuscated `test` job (emulator + probes) only fires when obfuscation infra itself changes (`gradle/obfuscate.init.gradle` or `apps/<app>/obfuscation/`) — runtime regressions from R8 are rare once keep-rules are settled. Mirror this locally with `./run_ci_local.sh apps/<app> --obfuscate`.

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

## Testing Zero-Day Tasks

Zero-day tasks use the same shared task-file contract as synthetic tasks; see
`documentation/TASK.md`. The zero-day-specific differences are documented in
`documentation/ZERODAY_TASKS.md`.

### Build Semantics

Zero-day tasks use inverted comparator logic vs synthetic
vulnerabilities:

- **Vulnerable APK** = baseline source as-is
- **Secure APK** = baseline source + task-local `fix.patch`

The baseline revision comes from `task/metadata.json` (`baseline.commit`).

### Running Validation

Local and external zero-day entry points share the same zero-day runner. `run_ci_local.sh` calls it directly for tasks under `apps/<app>/zero_day_vulnerabilities/`, while `scripts/validate_task_bundle.sh` is the CLI wrapper for invoking that same runner on an arbitrary task directory.

**Via `run_ci_local.sh`** (manages emulator lifecycle automatically):

```bash
./run_ci_local.sh apps/home-assistant-android \
  --test-zero-day-vuln zero_day_vulnerabilities/location_spoofing
```

**Direct validator** (emulator must already be running):

```bash
./scripts/validate_task_bundle.sh \
  --app home-assistant-android \
  --task-dir /path/to/task
```

**External report wrapper** (emulator must already be running):

```bash
./scripts/validate_zero_day_report.sh \
  --app home-assistant-android \
  --report-dir /path/to/reports/app-name/report-n
```

The supported hardened-build layout today is either the report-style checkout
above or the public-tree snapshot layout under
`apps/<app>/zero_day_vulnerabilities/<task_id>/`. In the report-style layout,
the validator uses `<report-dir>/artifacts/`; in the public-tree layout, it
uses `apps/<app>/zero_day_vulnerabilities/artifacts/<task_id>/`.
The task source itself remains source-only in both cases.

Compared with the current synthetic local CI path, zero-day validation:
1. runs from a temporary copy of the task directory so runtime artifacts do
   not get written back into the task checkout
2. uses the report or public-tree artifact root for `artifacts/` outputs and
   the hardened build manifest
3. builds the secure comparator from `fix.patch`
4. builds the vulnerable comparator from the unpatched `baseline.commit`

That validation path treats the task bundle as the primary execution source of
truth, while still keeping backward-compatible fallbacks to app metadata for
`package_name` and `commit_version`. It does not depend on any maintainer-
release timeline or disclosure schedule; publication metadata such as
`public_on` is handled separately by the disclosure pipeline in
`mobilecybench-zerodays` and is ignored by the validator.

## Flag injection utilities

`inject_flags.sh` is used by CI/baseline checks to place or remove flags:

```bash
./inject_flags.sh apps/<app_name>
./inject_flags.sh --remove apps/<app_name>
```

This operates on the APK in `apps/<app_name>/apk/` and the app's containers (if any).
