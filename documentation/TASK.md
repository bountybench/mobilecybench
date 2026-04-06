# Task Files

Synthetic tasks and zero-day tasks use the same task-level file conventions.
This document covers the shared pieces so the task-type docs only need to
explain what is different.

## Shared layout

```text
<task>/
├── metadata.json
├── prepare_app.sh              # Optional
├── exploit_files/
│   ├── exploit.sh
│   └── ...                     # Optional helper files
└── verify_files/
    ├── verify_exploit.sh
    └── ...                     # Optional helper files
```

Task-type-specific files are documented in:
- `documentation/SYNTHETIC_VULNERABILITIES.md`
- `documentation/ZERODAY_TASKS.md`

## Shared files

### `metadata.json`

Task-local metadata. The exact fields that matter differ by task type and are
spelled out in the task-type docs.

Rule of thumb: keep only task-specific information here. App-wide information
belongs in `apps/<app>/metadata.json`.

### `exploit_files/exploit.sh`

The reference exploit for the task.

Shared expectations:
- it runs inside the exploit container, not on the host
- it exits `0` on success and non-zero on failure
- it must not rely on privileged commands such as `adb root`, `su`, or
  `docker exec`
- every helper file it needs should live under `exploit_files/`

### `prepare_app.sh` (Optional)

A deterministic setup hook that runs on the host after the APK is installed and
before the exploit runs.

Use it for setup that must happen every run: seeding state, granting runtime
permissions, importing a victim identity, clearing leftover state, or opening
the app once to initialize storage.

### `verify_files/verify_exploit.sh`

The ground-truth verifier for the task.

Shared exit-code contract:
- `0` → the build is vulnerable
- `1` → the build is not vulnerable
- `2+` → the verifier itself failed

The verifier runs on the host, so it may inspect the emulator, backend
containers, databases, or filesystem directly.

## Shared execution model

### Where outputs should go

Task scripts should write outputs to `MCB_OUTPUT_DIR` when it is provided.

Why: some entry points run directly from the task checkout, while others first
copy the task into a temporary execution directory. Writing to the provided
output directory keeps the task portable across both modes.

### Shared environment variables

Validation and replay paths export these variables when running task hooks and
verifiers:

| Variable | Meaning |
|---|---|
| `MCB_TASK_DIR` | The task directory being executed |
| `MCB_OUTPUT_DIR` | Where task-generated outputs should be written |
| `MCB_APP_DIR` | `apps/<app>` directory |
| `MCB_TASK_METADATA_JSON` | Path to the task's `metadata.json` |
| `MCB_APP_METADATA_JSON` | Path to the app's `metadata.json` |
| `MCB_PACKAGE_NAME` | Android package name for the task |
| `MCB_TASK_ID` | Task identifier |
| `MCB_BASELINE_COMMIT` | Baseline commit, when the task type uses one |
| `MCB_PHASE` | Which comparator is currently being tested |

Some paths also provide task-type-specific variables such as `MCB_FIX_PATCH` or
`MCB_WORKSPACE_DIR`.

## Verifier design

The verifier should check a source of truth the exploit cannot fake.

Good examples:
- compare agent output against a secret value generated during setup
- inspect a database row or filesystem artifact that only a real exploit could
  create or read
- query backend state directly instead of grepping for an easily forged string

Bad examples:
- looking only for a hard-coded log line the exploit can print itself
- checking for a filename the exploit can create without triggering the bug
- relying on visible verifier patterns that can be copied directly

A simple test: if someone can read `verify_files/` and pass without actually
triggering the bug, the verifier is too weak.
