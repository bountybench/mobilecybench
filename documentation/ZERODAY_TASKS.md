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

That wrapper simply resolves `<report-dir>/task/` and delegates to
`validate_task_bundle.sh`.

## Validation behavior

Compared with synthetic-task validation, the zero-day validator does two extra
things:
- it copies the task into a temporary workspace before execution so the source
  checkout stays source-only
- it builds both comparators from `baseline.commit`, using `fix.patch` only for
  the secure build

The task directory itself should therefore contain only source files. Generated
artifacts such as `agent_output/`, `build/`, `dist/`, or Python cache
directories are rejected.
