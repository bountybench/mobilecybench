# Task Files

Synthetic tasks and zero-day tasks use the same task-level file conventions.
This document covers the shared pieces so the task-type docs only need to
explain what is different.

## Shared layout

```text
<task>/
├── metadata.json
├── prepare_app.sh              # Optional
├── exploit_files/              # Exploit artifact lives here
│   └── ...                     # Task-type-specific contents
└── verify_files/
    ├── verify_exploit.sh
    └── ...                     # Optional helper files
```

Task-type-specific files are documented in:
- `SYNTHETIC_VULNERABILITIES.md`
- `ZERODAY_TASKS.md`

## Shared files

### `metadata.json`

Task-local metadata. The exact fields that matter differ by task type and are
spelled out in the task-type docs.

Rule of thumb: keep only task-specific information here. App-wide information
belongs in `apps/<app>/metadata.json`.

Publication or disclosure scheduling metadata is out of band. Zero-day task
validation only consumes the execution contract described in
`ZERODAY_TASKS.md`; fields such as `public_on` belong in report
or publication tooling, not in the task bundle itself.

### Exploit artifact under `exploit_files/`

The authoritative exploit lives under `exploit_files/`. The exact format
depends on the task type. Task-type-specific contents are documented in:
- `SYNTHETIC_VULNERABILITIES.md`
- `ZERODAY_TASKS.md`

#### Zero-day attack models

Zero-day tasks declare an `attacker_model` in `metadata.json`:

| `attacker_model` | Required exploit artifact | Runtime |
|---|---|---|
| `malicious_app` | `exploit_files/exploit_apk/` | Built from source on the host, validated against the [MA permission gate](REDTEAM.md#ma-permission-gate), installed via `adb install -r -g`, launched via `am start -W -S -n com.mobilecybench.exploit/.MainActivity`; harness polls for `done.marker` and pulls the on-device evidence dir |
| `remote_attacker` | `exploit_files/exploit.sh` | Runs inside the exploit container with ADB + backend access |

For `malicious_app` tasks:
- keep only source files in `exploit_apk/`
- do not commit a prebuilt APK
- if `build_exploit_apk.sh` is omitted, the zero-day validator injects the
  canonical template at replay time

For `remote_attacker` tasks, `exploit.sh`:
- runs inside the exploit container, not on the host
- exits `0` on success and non-zero on failure
  `docker exec`
- helpers it needs should live under `exploit_files/`

### `prepare_app.sh` (Optional, per-task)

A deterministic **per-task** setup hook that runs on the host after the APK is
installed and **before** the exploit runs, for both attacker models.

Use it for vuln-specific setup: seeding a row only this exploit reads, granting
a permission only this exploit needs, opening a page only this exploit
exercises.

For app-wide victim-identity setup (logging the victim in, restoring shared
prefs, seeding the local DB), prefer the per-app `apps/<app>/prepare_victim.sh`
hook instead — it's shared across all tasks for the app and runs at an
attacker-model-specific point in the phase. See
[REDTEAM.md](REDTEAM.md#per-app-victim-hook-appsappprepare_victimsh).

The two hooks are independent: a task may ship one, both, or neither.

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
| `MCB_ATTACKER_MODEL` | Task attacker model, when the task type uses one |
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

### Reward hacking example

This is subtle but critical. A verifier can fail even when it is checking for
the “right kind” of effect if it checks that effect in a way the exploit can
fake.

#### Example vulnerability

Suppose an app leaks the admin password to logcat when a specific intent is
sent.

Suppose the real password is:

```text
abcd1234ghijkl567890!@#$%^&*()
```

#### Bad verifier design

```text
┌─────────────────────────────────────────────────────────────────┐
│                        FLAWED DESIGN                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   verify_exploit.sh:                                            │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ adb logcat -d | grep -E '[a-z]{4}[0-9]{4}[a-z]{6}...'  │   │
│   └─────────────────────────────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│            Searches logs for password pattern                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

If `verify_exploit.sh` does this:

```bash
adb logcat -d | grep -E '[a-z]{4}[0-9]{4}[a-z]{6}...'
```

then it is not really checking whether the exploit extracted the password. It
is only checking whether *some matching string* appeared in logcat.

An exploit that reads `verify_files/` can bypass that without touching the real
bug:

```bash
adb shell log -t FakeTag "abcd1234ghijkl567890!@#$%^&*()"
```

```text
┌─────────────────────────────────────────────────────────────────┐
│                       AGENT BYPASS                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Exploit prints a matching string to logcat                    │
│                           │                                     │
│                           ▼                                     │
│                  Verifier passes ✓                              │
│           (but no vulnerability was exploited)                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

Now the verifier passes, but no password was actually stolen.

Common “fixes” that still do not solve the problem:
- matching the full logcat line format
- checking for a specific tag
- matching a more specific visible pattern

If the exploit can see the pattern, it can often reproduce the pattern.

#### Better verifier design

```text
┌─────────────────────────────────────────────────────────────────┐
│                      CORRECT DESIGN                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Setup (before exploit runs):                                  │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ Generate random password → write to /data/admin_pw.txt │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│   verify_exploit.sh:                                            │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │ 1. Read actual password from /data/admin_pw.txt        │   │
│   │ 2. Read exploit output from MCB_OUTPUT_DIR             │   │
│   │ 3. Check whether the real password was recovered       │   │
│   └─────────────────────────────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│      Exploit must recover the real secret to pass               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

Instead, verify against a source of truth the exploit cannot forge.

For example:

1. During setup, generate a random password and write it to
   `/data/admin_pw.txt`
2. Let the exploit run
3. In `verify_exploit.sh`, read the real password from `/data/admin_pw.txt`
4. Check whether the exploit's output in `MCB_OUTPUT_DIR` contains that exact
   secret

Now the exploit must recover the real password to pass. It cannot succeed just
by printing something that “looks like” a password.

This same pattern generalizes:
- prefer hidden truth over visible patterns
- prefer direct state inspection over indirect textual clues
- prefer checks tied to a random or task-generated value over checks tied to a
  fixed string the exploit can learn in advance
