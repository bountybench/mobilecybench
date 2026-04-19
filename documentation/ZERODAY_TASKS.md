# Zero-Day Tasks

Zero-day tasks are the real-vulnerability counterpart to
`synthetic_vulnerabilities/`.

The shared task-file contract lives in `documentation/TASK.md`. This document
covers only what is different for zero-day tasks.

## What is different from synthetic tasks?

| Task type | Vulnerable APK | Secure APK |
|---|---|---|
| **Synthetic** | baseline + `vulnerability.patch` | baseline as-is |
| **Zero-day** | pinned baseline as-is | pinned baseline + `fix.patch` |

That difference leads to two zero-day-specific requirements:
1. the task must include a `fix.patch`
2. the task must pin the vulnerable source revision in `metadata.json`

## Directory structure

```text
apps/<app>/zero_day_vulnerabilities/<task_id>/
├── metadata.json
├── fix.patch
├── prepare_app.sh              # Optional; see TASK.md
├── exploit_files/
└── verify_files/
```

The same task can also live outside the public app tree under an external
report checkout as `<report-dir>/task/`.

## `fix.patch`

`fix.patch` is the task-local patch that turns the vulnerable baseline into the
secure comparator.

Unlike synthetic tasks, zero-day tasks do not use `vulnerability.patch`. The
vulnerability is already present in the pinned baseline commit.

## `metadata.json`

The validator only reads a small execution-focused subset of fields:

| Field | Why it exists |
|---|---|
| `schema_version` | Version marker for the documented zero-day metadata shape |
| `task_id` | Stable task identifier |
| `title` | Human-readable task name |
| `attacker_model` | Which exploit format and replay model the task uses |
| `baseline.commit` | The vulnerable source revision to build from |
| `build.env` | Optional task-specific build env vars |
| `runtime.package_name` | Optional package-name override |

Everything else is optional descriptive metadata. The validator ignores it.
That keeps the execution contract small while still leaving room for extra
classification or disclosure fields if a task owner wants them.

**Minimal example:**

```json
{
  "schema_version": 1,
  "task_id": "location_spoofing",
  "title": "Location spoofing via exported receiver",
  "attacker_model": "malicious_app",
  "baseline": {
    "commit": "23766ac"
  },
  "build": {
    "env": {
      "HOME_ASSISTANT_FLAVOR": "full"
    }
  },
  "runtime": {
    "package_name": "io.homeassistant.companion.android"
  }
}
```

## Attack models

Zero-day tasks support two replay models:

| `attacker_model` | Exploit artifact | What it represents |
|---|---|---|
| `malicious_app` | `exploit_files/exploit_apk/` | Unprivileged app on the victim device |
| `remote_attacker` | `exploit_files/exploit.sh` | Authenticated low-privilege user acting from a separate device/session |

The validator uses the same high-level attacker split as the red-team
workflow:

- **`malicious_app`**: install target APK → run `prepare_app.sh` if present →
  run app-level `prepare_victim.sh` if present → replay the exploit APK on the
  same emulator → run `verify_exploit.sh`
- **`remote_attacker`**: install target APK → run `prepare_app.sh` if present →
  replay `exploit.sh` in the exploit container → `adb shell pm clear
  <package>` to wipe app-local state → run app-level `prepare_victim.sh` if
  present → run `verify_exploit.sh`

The optional app-level `prepare_victim.sh` hook lives under `apps/<app>/` and
is owned by the app integration, not by the task bundle. Zero-day validation
reuses it when present so task replay matches the intended victim-session
timing for each attack model.

## Building and validating

### Build the two comparators directly

```bash
# Vulnerable comparator: pinned baseline as-is
./build_apk.sh home-assistant-android --commit 23766ac

# Secure comparator: same baseline + task-local fix.patch
./build_apk.sh home-assistant-android \
  --commit 23766ac \
  --hardened-patch /path/to/task/fix.patch
```

### Validate through local CI

```bash
./run_ci_local.sh apps/home-assistant-android \
  --test-zero-day-vuln zero_day_vulnerabilities/location_spoofing
```

### Validate a task directory directly

```bash
./scripts/validate_task_bundle.sh \
  --app home-assistant-android \
  --task-dir /path/to/task
```

### Validate a task stored under an external report directory

```bash
./scripts/validate_zero_day_report.sh \
  --app home-assistant-android \
  --report-dir /path/to/reports/home-assistant-android/report-1
```

`validate_zero_day_report.sh` simply resolves `<report-dir>/task/`. Both it and the local `run_ci_local.sh --test-zero-day-vuln ...` path then use the same shared zero-day runner; `validate_task_bundle.sh` is the direct CLI entry point to that runner.

## Validation behavior

Compared with the current synthetic local CI path, the zero-day validator
does two extra things:
- it runs from a temporary copy of the task directory before execution, so
  runtime artifacts do not get written back into the task checkout
- it builds both comparators from `baseline.commit`, using `fix.patch` only for
  the secure build

The task directory itself should therefore contain only source files. Generated
artifacts such as `agent_output/`, `build/`, `dist/`, or Python cache
directories are rejected.
