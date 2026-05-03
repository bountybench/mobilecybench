#!/usr/bin/env python3
"""Bring an app to a warm-state and save an AVD snapshot.

Wires the existing harness scripts (``start_emulator.sh``,
``start_runtime.sh``, ``utils/inject_system_ca.sh``) plus the per-app
victim setup, and then snapshots the resulting state. The snapshot
becomes the starting point for probe-gen iteration: subsequent gate
runs ``avd_snapshot load`` and skip the ~7m17s warm-up phase.

What "warm" means here:
  - Emulator booted, ADB connected
  - Backends started via ``apps/<app>/start_runtime.sh``
  - System CA injected (if applicable)
  - APK installed
  - App launched
  - Victim user logged in (via per-app ``prepare_victim.sh`` if present)
  - Initial sync settled

The script does NOT apply a vulnerability patch — it builds against the
clean APK so the snapshot is reusable across any synthetic vuln targeting
the same app+commit.

Usage::

    # First run: bring up + snapshot
    python probe_gen/scripts/warm_cycle.py --app conversations --snapshot warm-conversations

    # Subsequent runs: just restore (use avd_snapshot.py directly)
    python probe_gen/scripts/avd_snapshot.py load --name warm-conversations

Requires ``JAVA_HOME`` and ``ANDROID_HOME`` to be set in the environment
(see DESIGN.md §"Side issues fixed during profiling").
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from probe_gen.pipeline.snapshots import (  # noqa: E402
    SnapshotError,
    avd_snapshot_save,
    has_snapshot,
)


def _resolve_bash() -> str:
    """Pick Git Bash on Windows; plain bash elsewhere.

    Mirrors the same bash-resolution policy as ``profile_probe_run.py``.
    """
    bash = shutil.which("bash")
    return bash or "bash"


def _run_step(name: str, cmd: list[str], cwd: Path) -> None:
    """Run a subprocess step, streaming output, raising on failure."""
    print(f"\n[warm-cycle] {name}", file=sys.stderr)
    print(f"[warm-cycle] $ {' '.join(cmd)}", file=sys.stderr)
    t0 = time.monotonic()
    proc = subprocess.run(cmd, cwd=str(cwd))
    dt = time.monotonic() - t0
    if proc.returncode != 0:
        print(
            f"[warm-cycle] FAILED ({name}, rc={proc.returncode}, {dt:.1f}s)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    print(f"[warm-cycle] {name} OK ({dt:.1f}s)", file=sys.stderr)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--app", required=True, help="App name (apps/<app>)")
    p.add_argument(
        "--snapshot",
        required=True,
        help="AVD snapshot name to save the warm state under",
    )
    p.add_argument(
        "--sdk",
        default="35",
        help="Emulator SDK version (default: 35; matches metadata.json)",
    )
    p.add_argument(
        "--skip-emulator",
        action="store_true",
        help="Don't (re)start the emulator. Use when an emulator is already running.",
    )
    p.add_argument(
        "--skip-snapshot-save",
        action="store_true",
        help="Bring the system to warm state but don't save the snapshot. "
        "Useful for debugging the warm-up sequence.",
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="If a snapshot with --snapshot name exists, delete it before saving.",
    )
    args = p.parse_args(argv)

    repo_root = _REPO_ROOT
    app_dir = repo_root / "apps" / args.app
    if not app_dir.is_dir():
        print(f"[warm-cycle] app dir not found: {app_dir}", file=sys.stderr)
        return 2

    bash = _resolve_bash()

    # Pre-flight: confirm JAVA_HOME / ANDROID_HOME are set since the
    # warm-up will fail downstream otherwise. We don't override.
    if not os.environ.get("JAVA_HOME") or not os.environ.get("ANDROID_HOME"):
        print(
            "[warm-cycle] WARNING: JAVA_HOME or ANDROID_HOME not set; "
            "downstream scripts may fail. See DESIGN.md.",
            file=sys.stderr,
        )

    overall_t0 = time.monotonic()

    # 1. Stop any stale emulator (no-op if none running)
    _run_step("stop stale emulator", [bash, "stop_emulator.sh"], repo_root)

    # 2. Start emulator
    if not args.skip_emulator:
        _run_step(
            "start emulator",
            [bash, "start_emulator.sh", args.sdk],
            repo_root,
        )

    # 3. Inject system CA. Best-effort — the script may fail on Windows
    # path translation but the rest of the cycle still works.
    ca_script = repo_root / "utils" / "inject_system_ca.sh"
    if ca_script.exists():
        try:
            _run_step("inject system CA", [bash, str(ca_script)], repo_root)
        except SystemExit:
            print(
                "[warm-cycle] CA injection failed; continuing (HTTPS to backends "
                "may be untrusted, harmless for non-TLS-pinned probes)",
                file=sys.stderr,
            )

    # 4. Run the app's start_runtime.sh — builds backends, installs APK,
    # logs in via prepare_victim.sh if present.
    _run_step(
        f"start runtime ({args.app})",
        [bash, "./start_runtime.sh"],
        app_dir,
    )

    # 5. Snapshot
    overall_dt = time.monotonic() - overall_t0
    print(
        f"\n[warm-cycle] system warm in {overall_dt:.1f}s ({int(overall_dt // 60)}m{int(overall_dt) % 60:02d}s)",
        file=sys.stderr,
    )

    if args.skip_snapshot_save:
        print(
            "[warm-cycle] --skip-snapshot-save set; not snapshotting", file=sys.stderr
        )
        return 0

    try:
        if has_snapshot(args.snapshot):
            if not args.overwrite:
                print(
                    f"[warm-cycle] snapshot {args.snapshot!r} already exists; "
                    f"pass --overwrite to replace",
                    file=sys.stderr,
                )
                return 1
            from probe_gen.pipeline.snapshots import avd_snapshot_delete

            print(
                f"[warm-cycle] overwriting existing snapshot {args.snapshot!r}",
                file=sys.stderr,
            )
            avd_snapshot_delete(args.snapshot)
    except SnapshotError as exc:
        # has_snapshot probe shouldn't hard-fail the cycle. Log and proceed.
        print(f"[warm-cycle] snapshot list check failed: {exc}", file=sys.stderr)

    print(f"\n[warm-cycle] saving snapshot {args.snapshot!r}...", file=sys.stderr)
    snap_t0 = time.monotonic()
    try:
        avd_snapshot_save(args.snapshot)
    except SnapshotError as exc:
        print(f"[warm-cycle] snapshot save failed: {exc}", file=sys.stderr)
        return 1
    snap_dt = time.monotonic() - snap_t0
    print(f"[warm-cycle] saved in {snap_dt:.1f}s", file=sys.stderr)

    print("\n[warm-cycle] DONE", file=sys.stderr)
    print(
        f"[warm-cycle] for subsequent iterations, use:\n"
        f"  python probe_gen/scripts/avd_snapshot.py load --name {args.snapshot}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
