# Environment-Failure Diagnosis for jitsi-meet Gold-Run

> Companion to `integration_test_log.md`. The integration test
> hit 7 distinct environment / harness failures while trying to
> drive the runner end-to-end. This document classifies each one
> as **bug-fix** (real harness bug worth patching) vs
> **environment** (host-config issue documented but not a code
> change), and proposes specific fixes for the bugs.

---

## Failure 1 — Pre-existing emulator blocks runner

**Verbatim:**
```
RuntimeError: Running emulator(s) detected: emulator-5554

The runner manages its own emulator — please stop all emulators first:

  ./stop_emulator.sh          # or: adb -s <device> emu kill
```

**Source:** `utils/emulator_manager.py:319-326`. The runner explicitly
refuses to attach to an externally-started emulator.

**Classification:** **environment**. The runner's design choice is
deliberate: the runner needs to control the emulator's lifecycle
(boot args, restart between phases, capture logcat, etc.) and an
externally-launched emulator may have different settings. The
error message is helpful and points at the workaround.

**Recommendation:** No code change. Document in
`documentation/GETTING_STARTED.md` (or a new
`documentation/TROUBLESHOOTING.md` section) that running the
runner requires no live emulators. Optionally, add an
auto-cleanup flag (`--force-stop-emulator`) — but this is
ergonomic, not safety-critical.

---

## Failure 2 — `pip install -e .` fails with PEP 668

**Verbatim:**
```
2026-04-26 15:31:17,730 - MobileCyBench.emulator_manager - ERROR - Setup failed: error: externally-managed-environment

× This environment is externally managed
╰─> To install Python packages system-wide, try brew install xyz, where xyz is the package you are trying to install.
    ...
    You may restore the old behavior of pip by passing
    the '--break-system-packages' flag to pip, or by adding
```

**Source:** `setup.sh:637` runs `pip install -e .` unconditionally.
On a Homebrew-managed Python 3.12 (the default on recent macOS),
PEP 668 blocks system-wide installs.

**Classification:** **harness bug**. Real fix needed; affects every
new contributor on macOS who tries to run the harness.

**Proposed fix** (`setup.sh:637`):

```bash
# Detect PEP 668 / externally-managed Python and pass the explicit flag.
PIP_FLAGS=""
if python3 -c 'import sys; sys.exit(0 if hasattr(sys, "_base_executable") else 1)' 2>/dev/null; then
    if python3 -c 'import sysconfig, os; \
        marker = os.path.join(sysconfig.get_path("stdlib"), "EXTERNALLY-MANAGED"); \
        sys.exit(0 if os.path.exists(marker) else 1)' 2>/dev/null; then
        PIP_FLAGS="--break-system-packages"
    fi
fi
pip install $PIP_FLAGS -e .
```

Or simpler: respect the `PIP_BREAK_SYSTEM_PACKAGES=1` env var and
include it when needed. The simplest possible patch:

```bash
PIP_BREAK_SYSTEM_PACKAGES="${PIP_BREAK_SYSTEM_PACKAGES:-1}" pip install -e .
```

(Sets the env var only if not already set; leaves the behavior
identical on Linux CI.)

---

## Failure 3 — Port 8080 collision

**Verbatim:**
```
Error response from daemon: failed to set up container networking:
driver failed programming external connectivity on endpoint
jitsi-latest-jvb-1: Bind for 0.0.0.0:8080 failed: port is already
allocated
```

**Source:** `apps/jitsi-meet/jitsi-docker/jitsi-latest/docker-compose.yml`
maps the JVB container's port 8080 to host 8080. Any other container
holding that port blocks the bring-up.

In the integration test, an unrelated `ntfy-server` container (from
a different app's compose) was holding 8080.

**Classification:** **environment** (mostly), with a minor
**harness bug**: the runner could detect the conflict pre-flight
and emit a clearer error than the docker daemon's networking
exception.

**Recommendation:** No code change to the docker-compose (the
upstream jitsi compose maps 8080 by design). For the runner, an
optional pre-flight check in `setup_utils.py:install_app_and_setup_backend`:

```python
def _check_app_ports_free(app_dir: Path) -> None:
    compose = app_dir / "jitsi-docker/jitsi-latest/docker-compose.yml"
    # parse compose, collect host-side port mappings, verify lsof clean
    ...
```

This is a nice-to-have — not blocking. The error message from
docker is already actionable to anyone who reads it.

---

## Failure 4 — `--init` contract broken (caused by my probe replacement)

**Verbatim:**
```
2026-04-26 15:35:08,854 - MobileCyBench - INFO - [PASS] app_files_flag_unchanged: flag.txt absent; benign
2026-04-26 15:35:09,572 - MobileCyBench - INFO - [PASS] custom_plugins_dir_empty: prosody-plugins-custom is empty (as seeded)
```

**Source:** My commit `911fb4c7` replaced `apps/jitsi-meet/test_integrity.py`
without preserving the legacy `--init` branch that
`apps/jitsi-meet/start_runtime.sh:172` depends on.

**Classification:** **fixed in commit `3213943f`**. Already shipped
with `init_baseline()` shim and module-level `compute_hash()`.

---

## Failure 5 — Emulator process died on second boot

**Verbatim:**
```
2026-04-26 15:36:14,494 - MobileCyBench.emulator_manager - INFO - Emulator process started with PID: 11814
2026-04-26 15:36:21,370 - MobileCyBench.emulator_manager - INFO - Detected our emulator device: emulator-5554
2026-04-26 15:36:21,370 - MobileCyBench.emulator_manager - INFO - Waiting for emulator-5554 to complete boot...
..2026-04-26 15:36:30,573 - MobileCyBench.emulator_manager - ERROR - Emulator process terminated unexpectedly
RuntimeError: Emulator process died during boot
```

**Source:** `utils/emulator_manager.py:436-446`. The Python
`subprocess.Popen` for the qemu-system-aarch64 process polls
non-None within ~9 seconds of starting.

**Classification:** **environment** (memory pressure on macOS
host) but with a **partial harness bug**: the runner does not
clean up the dead device entry from adb-server, which causes
cascading failures #6 and #7.

**Memory observation during test:**

```
$ vm_stat | head -3
Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                5490.    # ~85 MB free
Pages active:                            298674.    # ~4.6 GB active
$ sysctl vm.swapusage
vm.swapusage: total = 20480.00M  used = 19138.25M  free = 1341.75M
```

System had 24 GB total RAM but swap was nearly exhausted (19/20 GB
used). The third emulator boot in the same run (initial setup +
Phase 1 + Phase 2) pushed the qemu-system process over the edge.

**Recommendation:**

1. **Environment**: ensure the host has enough free memory; close
   other heavy apps before running. This is a Mac-laptop-class
   issue; CI hosts typically don't see it.
2. **Harness improvement** (orthogonal to memory): when
   `wait_until_ready` raises `Emulator process died during boot`,
   the cleanup path should run `adb kill-server; adb start-server`
   to purge stale device entries before the next attempt. Currently
   the dead entry persists into the next run, causing failures 6/7.

   Specific patch (`utils/emulator_manager.py:443-446`):

   ```python
   logger.error("Emulator process terminated unexpectedly")
   self.state = EmulatorState.STOPPED
   # NEW: purge stale device entry so the next emulator can attach cleanly.
   subprocess.run(["adb", "kill-server"], capture_output=True, timeout=10)
   msg = "Emulator process died during boot"
   ```

---

## Failure 6 — "more than one device/emulator" between runs

**Verbatim:**
```
2026-04-26 15:40:53,208 - MobileCyBench - INFO - Injecting system CA certificate...
2026-04-26 15:40:53,341 - MobileCyBench - ERROR - CA injection failed (exit 1)
stderr: error: more than one device/emulator
RuntimeError: System CA injection failed
```

**Source:** `utils/inject_system_ca.sh` runs every `adb` command
without a `-s <serial>` flag (lines 280-308 and throughout the
helper functions). When adb-server has more than one device entry
(e.g., a stale entry from a crashed prior emulator that wasn't
cleaned up by Failure 5), every command errors.

**Classification:** **harness bug**. Real fix needed; this is
the most impactful bug because it converts a transient emulator
crash into a persistent run-blocker.

**Proposed fix** (two complementary patches):

**Patch A — `utils/inject_system_ca.sh` should pin to a serial:**

Add at the top of the script (after `CERT_PATH` resolution):

```bash
# Honor ANDROID_SERIAL from the environment; otherwise auto-detect
# the most-recently-attached emulator. Set ADB_OPTS so every adb
# command in this script targets the right device.
if [[ -z "${ANDROID_SERIAL:-}" ]]; then
    ANDROID_SERIAL="$(adb devices | awk '/^emulator-/ {print $1}' | tail -1)"
    [[ -n "$ANDROID_SERIAL" ]] || fatal "No emulator device visible to adb"
fi
ADB="adb -s $ANDROID_SERIAL"
log_info "Targeting device $ANDROID_SERIAL"
```

Then replace every `adb root`, `adb wait-for-device`, `adb shell ...`,
`adb push ...` with `$ADB root`, etc.

That makes the script deterministic regardless of adb-server's
device list.

**Patch B — `utils/emulator_certs.py` should pass the serial:**

Where `inject_system_ca.sh` is invoked, set `ANDROID_SERIAL` from
the `EmulatorManager` instance:

```python
# utils/emulator_certs.py
def inject_system_ca(project_root: Path, emulator_serial: str | None = None) -> None:
    script = project_root / "utils" / "inject_system_ca.sh"
    env = os.environ.copy()
    if emulator_serial:
        env["ANDROID_SERIAL"] = emulator_serial
    result = subprocess.run([str(script)], env=env, ...)
    ...
```

And in `workflows/base.py:_restart_runtime`:

```python
inject_system_ca(self.project_root, emulator_serial=self.emulator.serial)
```

Patch A alone is enough to fix the immediate bug. Patch B is the
robust long-term fix.

---

## Failure 7 — same as #6 but on Phase 1 emulator restart

**Verbatim:**
```
2026-04-26 15:43:50 - RESTARTING EMULATOR
2026-04-26 15:43:50 - STOPPING EMULATOR (Killing specific device: emulator-5554)
2026-04-26 15:43:59 - WAITING FOR EMULATOR TO BOOT
2026-04-26 15:44:40 - Device emulator-5554 boot completed!
2026-04-26 15:44:43 - Injecting system CA certificate...
2026-04-26 15:44:43 - ERROR - CA injection failed (exit 1)
                       stderr: error: more than one device/emulator
```

**Source:** Same as Failure 6 — `inject_system_ca.sh` not
device-pinned. The kill + restart sequence in `emulator_manager.py`
sometimes leaves a stale device entry visible to adb between the
old and new emulator.

**Classification:** **harness bug**. Same root cause as #6, same
fix (Patch A above resolves both).

**Recommendation:** Apply Patch A. Optionally also add an
`adb reconnect offline` or `adb kill-server` step in
`emulator_manager.py:STOPPING_EMULATOR` after `adb -s <device> emu kill`
returns, to forcibly clear the device list.

---

## Summary table

| # | Failure | Class | Recommended fix | Effort |
|---|---------|-------|----------------|--------|
| 1 | Pre-existing emulator blocks runner | env | Document in TROUBLESHOOTING.md | trivial |
| 2 | PEP 668 `pip install -e .` | bug | `PIP_BREAK_SYSTEM_PACKAGES=1` in setup.sh | 1 line |
| 3 | Port 8080 collision | env | Optional pre-flight check; document | nice-to-have |
| 4 | `--init` contract | bug | Already fixed in commit 3213943f | done |
| 5 | Emulator process died on second boot | env + bug | Purge stale adb device entry on death; document memory requirements | ~5 lines |
| 6 | "more than one device" between runs | bug | Pin inject_system_ca.sh to ANDROID_SERIAL | ~15 lines |
| 7 | "more than one device" on Phase 1 restart | bug | Same as #6 | (same fix) |

**Of the 7 failures, 5 are real harness bugs worth fixing.**
Failures 1 and 3 are environment/host issues that should be
documented but don't need code changes.

The single highest-impact fix is **Patch A on `inject_system_ca.sh`**
(make it `-s <serial>` aware): that alone resolves #6 and #7,
which together account for most of the integration-test
failure attempts.
