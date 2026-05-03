#!/usr/bin/env python3
"""CLI wrapper for AVD snapshot operations (Phase 0.1 Tier 1).

Subcommands:
  save    Save the current emulator state under a name
  load    Restore the emulator to a named snapshot
  list    Enumerate snapshots on the running emulator
  delete  Delete a named snapshot

Requires a running emulator (the harness's single-emulator policy
applies — see ``emulator.py``). Failures raise non-zero exit and print
the underlying ``adb emu`` error to stderr.

Usage::

    # After the runtime is fully warm (emulator booted, backend up,
    # logged in, sync settled — typically the state at the end of a
    # successful Phase 1 from run_ci_local.sh):
    python probe_gen/scripts/avd_snapshot.py save --name warm-conversations

    # Per-iteration restore (replaces ~7m17s emulator+backend+login+sync
    # cost with ~10–20s):
    python probe_gen/scripts/avd_snapshot.py load --name warm-conversations

    python probe_gen/scripts/avd_snapshot.py list
    python probe_gen/scripts/avd_snapshot.py delete --name warm-conversations
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from probe_gen.pipeline.snapshots import (  # noqa: E402
    SnapshotError,
    avd_snapshot_delete,
    avd_snapshot_list,
    avd_snapshot_load,
    avd_snapshot_save,
)


def _cmd_save(args: argparse.Namespace) -> int:
    t0 = time.monotonic()
    try:
        avd_snapshot_save(args.name, timeout=args.timeout)
    except SnapshotError as exc:
        print(f"[avd-snapshot] save failed: {exc}", file=sys.stderr)
        return 1
    dt = time.monotonic() - t0
    print(f"[avd-snapshot] saved {args.name!r} in {dt:.1f}s", file=sys.stderr)
    return 0


def _cmd_load(args: argparse.Namespace) -> int:
    t0 = time.monotonic()
    try:
        avd_snapshot_load(args.name, timeout=args.timeout)
    except SnapshotError as exc:
        print(f"[avd-snapshot] load failed: {exc}", file=sys.stderr)
        return 1
    dt = time.monotonic() - t0
    print(f"[avd-snapshot] loaded {args.name!r} in {dt:.1f}s", file=sys.stderr)
    return 0


def _cmd_list(_args: argparse.Namespace) -> int:
    try:
        snapshots = avd_snapshot_list()
    except SnapshotError as exc:
        print(f"[avd-snapshot] list failed: {exc}", file=sys.stderr)
        return 1
    if not snapshots:
        print("(no snapshots)", file=sys.stderr)
        return 0
    for snap in snapshots:
        print(snap.name)
    return 0


def _cmd_delete(args: argparse.Namespace) -> int:
    try:
        avd_snapshot_delete(args.name, timeout=args.timeout)
    except SnapshotError as exc:
        print(f"[avd-snapshot] delete failed: {exc}", file=sys.stderr)
        return 1
    print(f"[avd-snapshot] deleted {args.name!r}", file=sys.stderr)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    p_save = sub.add_parser(
        "save", help="Save current emulator state as a named snapshot"
    )
    p_save.add_argument(
        "--name", required=True, help="Snapshot name (alphanumeric/_./-)"
    )
    p_save.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="adb-emu timeout in seconds (default: 300; snapshots can be slow)",
    )
    p_save.set_defaults(func=_cmd_save)

    p_load = sub.add_parser("load", help="Restore emulator to a named snapshot")
    p_load.add_argument("--name", required=True)
    p_load.add_argument("--timeout", type=int, default=120)
    p_load.set_defaults(func=_cmd_load)

    p_list = sub.add_parser("list", help="List snapshots on the running emulator")
    p_list.set_defaults(func=_cmd_list)

    p_del = sub.add_parser("delete", help="Delete a named snapshot")
    p_del.add_argument("--name", required=True)
    p_del.add_argument("--timeout", type=int, default=60)
    p_del.set_defaults(func=_cmd_delete)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
