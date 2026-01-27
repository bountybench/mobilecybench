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
  setup.sh
  setup_app_source.sh
```

Full CI (recommended):

```
apps/<app_name>/
  codebase/
  metadata.json
  secrets.json
  setup.sh
  setup_app_source.sh
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
- `download_link`: stable release APK URL (if not building from source)
- `emulator_server`: server address reachable from emulator (10.0.2.2)
- `app_server`: server address reachable inside Docker network
- `username` / `password`: credentials the agent can use
- `container_names`: Docker containers to monitor for availability

## 6) Build the APK (preferred path)

Use `setup_app_source.sh` to build a release APK and copy it to:

```
apps/<app_name>/apk/<app_name>.apk
```

Rules:

- Do not install the APK in `setup_app_source.sh`.
- Prefer a release build and a universal APK.
- If the APK path changes, validate it explicitly and fail fast.

If you cannot build from source, set `download_link` in `metadata.json`.

## 7) Install and setup the app

`setup.sh` should:

- Install and configure any server dependencies (Docker if needed).
- Install the APK from `apps/<app_name>/apk/<app_name>.apk`.
- Launch the app.

Avoid `sleep` in favor of health checks.

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

## Minimal required files (for any app)
Every app must provide an APK by either:
- `apps/<app_name>/setup_app_source.sh` (preferred), or
- `apps/<app_name>/metadata.json` with `download_link`

At least one of these is mandatory.

## Full working example: Conversations

Use `apps/conversations/` as a known‑good reference for a complete app integration.

Key files to study:

- `apps/conversations/metadata.json`
- `apps/conversations/setup_app_source.sh`
- `apps/conversations/setup.sh`
- `apps/conversations/secrets.json`
- `apps/conversations/test_confidentiality.py`
- `apps/conversations/test_integrity.py`
- `apps/conversations/test_availability.py`
- `apps/conversations/test_access_control.py`
- `apps/conversations/vuln_scenarios/`
- `apps/conversations/cleanup.sh`

Recommended local validation (build + full checks):

```bash
./run_ci_local.sh apps/conversations
```

## Common build checks

Before writing `setup_app_source.sh`, inspect the app:

```bash
ls *.gradle* *.kts
cat gradle/wrapper/gradle-wrapper.properties
./gradlew tasks --group=build
```

Look for:

- Build variants (debug, release, flavors)
- Required Java version
- APK output location

## Repo map (key directories)
- `apps/`: All benchmark apps and their scripts/metadata.
- `runner.py`: Main experiment entry point.
- `setup.sh`: Installs Android SDK, creates AVD, generates emulator scripts.
- `start_emulator.sh`, `stop_emulator.sh`, `check_device.sh`: Emulator helpers (generated by setup).
- `run_ci_local.sh`: Local CI validation for an app.
- `run_checks.sh`: Standard probe runner used in CI and by the runner.
- `tools/`: Utility scripts (static analysis helpers, APK publishing, etc.).
- `agent/`: AI agent code and runtime.
