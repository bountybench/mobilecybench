# Adding an App to the Benchmark

This guide is the canonical checklist for creating a new `apps/<app_name>/` entry.

## 0) Add the target repo to cy-suite (if needed)

We maintain isolated copies of target repositories in the **cy-suite** organization.

If you do not have access to **cy-suite**, ask Thomas, Nardos or Wai to update your access. Otherwise:

1. Navigate to https://github.com/cy-suite and select **New**.
2. Select **Import a repository**.
3. Enter the URL for the Android app repo.
4. Set **owner** to **cy-suite** and keep it **Private**.

## 1) Confirm the target repo

We keep isolated copies of target apps under the `cy-suite` GitHub organization.

- If you do not have access, ask a core team member to import the repo into `cy-suite`.
- You will use the `cy-suite` URL as a git submodule inside `apps/<app_name>/codebase/`.

## 2) Create the app directory

Create a new folder under `apps/`:

```
apps/<app_name>/
```

## 3) Add the submodule

Add the target app repo under `codebase/` as a submodule from `cy-suite`.
Your scripts should assume the codebase is already checked out to the commit in `metadata.json`.

```bash
git submodule add <cy-suite_url>
```

## 4) Add required files

Minimum for simple CI:

```
apps/<app_name>/
  codebase/
  metadata.json
  build.sh
  start_runtime.sh
```

Full CI (recommended):

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

## 5) Fill out metadata.json

Required fields (most important):

- `commit_version`: commit hash for the app repo
- `sdk`: target SDK version
- `java`: required Java version for builds
- `package_name`: Android package name
- `gh_link`: `cy-suite` GitHub link
- `download_link`: GitHub release URL for prebuilt APKs (use `publish_apk_bundle.sh` to create)
- `emulator_server`: server address reachable from emulator (10.0.2.2)
- `app_server`: server address reachable inside Docker network
- `username` / `password`: credentials the agent can use
- `container_names`: Docker containers to monitor for availability

## 6) Write build.sh

`build.sh` should be minimal — only the build command and APK copy. Everything else (Java, Android SDK, signing, codebase checkout) is handled by the root `build_apk.sh` wrapper.

```bash
#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/codebase"

./gradlew assembleRelease --no-daemon

cp app/build/outputs/apk/release/app-release-unsigned.apk "$SCRIPT_DIR/unsigned.apk"
```

- Output must be `$SCRIPT_DIR/unsigned.apk`
- Don't handle signing, Java setup, or codebase checkout — `build_apk.sh` does all of that
- Keystore env vars (`KEYSTORE_PATH`, `KEYSTORE_PASSWORD`, `KEYSTORE_ALIAS`, `KEYSTORE_ALIAS_PASSWORD`) are available if gradle needs them
- Prefer universal APKs for emulator compatibility
- App-specific build patches (SDK upgrades, dependency fixes, ProGuard rules, etc.) belong here
- Keep it simple — most `build.sh` scripts are 10-20 lines

Build and publish the APK:
```bash
./build_apk.sh <app_name>
./publish_apk_bundle.sh apps/<app_name>
```

If you cannot build from source, publish a prebuilt APK using `publish_apk_bundle.sh` — this uploads to a GitHub release on our repo and auto-updates `download_link` in `metadata.json`.

**Important:** Always republish APKs after changing `commit_version`. The published APKs must match the commit in `metadata.json`.

## 7) Write start_runtime.sh

`start_runtime.sh` installs and sets up the app at runtime. Every script starts with this standard header:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../utils/android.sh"
APK_PATH=$(parse_apk_path "$SCRIPT_DIR" "<app_name>" "$@")
cd "$SCRIPT_DIR"
```

Sourcing `utils/android.sh` gives you `parse_apk_path`, `adb_install_apk`, `wait_healthy`, `log_info`, `fatal`, and other helpers. `parse_apk_path` handles the `--apk <path>` override automatically.

After the header:

- Start server containers (Docker) if needed (use `wait_healthy` instead of `sleep`).
- Install the APK via `adb_install_apk "$APK_PATH"`.
- Launch the app.

Python scripts (seeding, UI automation) should use the root-level venv — apps should not have their own `requirements.txt` or virtual environments.

## 8) Add probes and scenarios

To enable full CI and evaluation, implement the four probes:

- `test_confidentiality.py`
- `test_integrity.py`
- `test_availability.py`
- `test_access_control.py`

Add scenario scripts under `vuln_scenarios/` that intentionally cause violations:

- `vuln_scenario_0` for non-DoS violations
- `vuln_scenario_1` for DoS scenarios (only if app uses servers)

## 9) Validate locally

Run:

```bash
./run_ci_local.sh apps/<app_name>
```

This mirrors the CI behavior (simple or full depending on which probe scripts exist).

## APK sourcing (source vs download vs skip)

Every app must have `download_link` in `metadata.json` pointing to a GitHub release on our repo. Use `publish_apk_bundle.sh` to create releases. If the app also has `build.sh`, local CI can run both download and source-build modes:

```bash
./run_ci_local.sh apps/<app_name>                 # run all available modes
./run_ci_local.sh apps/<app_name> --skip-build    # download-only
./run_ci_local.sh apps/<app_name> --skip-download # source-only
./run_ci_local.sh apps/<app_name> --skip-apk      # reuse existing APKs
```

## Full working example: Conversations

Use `apps/conversations/` as a known‑good reference for a complete app integration.

Key files to study:

- `apps/conversations/metadata.json`
- `apps/conversations/build.sh`
- `apps/conversations/start_runtime.sh`
- `apps/conversations/cleanup.sh`
- `apps/conversations/secrets.json`
- `apps/conversations/test_confidentiality.py`
- `apps/conversations/test_integrity.py`
- `apps/conversations/test_availability.py`
- `apps/conversations/test_access_control.py`
- `apps/conversations/vuln_scenarios/`

Recommended local validation (build + full checks):

```bash
./run_ci_local.sh apps/conversations
```

## Common build checks

Before writing `build.sh`, inspect the codebase:

```bash
ls *.gradle* *.kts
cat gradle/wrapper/gradle-wrapper.properties
./gradlew tasks --group=build
```

Look for: build variants (debug, release, flavors), required Java version, APK output location.

## Repo map

- `build_apk.sh`: Centralized APK build wrapper (handles env, signing, output)
- `publish_apk_bundle.sh`: Publishes APK bundle to GitHub release, updates `download_link`
- `apps/<app>/build.sh`: Per-app build script (outputs `unsigned.apk`)
- `apps/<app>/start_runtime.sh`: Installs APK, starts containers, launches app
- `apps/<app>/cleanup.sh`: Tears down containers, uninstalls app
- `run_ci_local.sh`: Local CI validation
- `run_checks.sh`: Probe runner used by CI and by the runner
- `runner.py`: Main experiment entry point
- `setup.sh`: Installs Android SDK, creates AVD, generates emulator scripts
- `start_emulator.sh`, `stop_emulator.sh`, `check_device.sh`: Emulator helpers (generated by setup).
- `utils/`: Shared shell and Python utilities (`android.sh`, `common.sh`, `wait.sh`, `docker.sh`, `ui_utils.py`, etc.)
- `tools/`: Utility scripts (static analysis helpers, etc.)
- `agent/`: AI agent code and runtime
