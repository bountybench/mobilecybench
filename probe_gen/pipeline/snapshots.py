"""Emulator AVD snapshot save/restore — Phase 0.1 Tier 1 implementation.

Wraps ``adb emu avd snapshot save|load|list|del`` so probe-gen iteration
can collapse the per-iteration cost (emulator boot + backend up + app
install + login + initial sync) from ~7m17s to ~10–20s.

Operations require a running, single-emulator setup (matches the existing
benchmark harness's "single-emulator policy" — see ``emulator.py``).

Snapshots are an emulator-image feature; they include kernel/RAM state
plus virtual disk deltas. Backend container state (docker-compose
volumes) is *not* covered by this module — the caller must pair AVD
restore with backend-state restore where backend state matters.

Public surface:
  - :func:`avd_snapshot_save`
  - :func:`avd_snapshot_load`
  - :func:`avd_snapshot_list`
  - :func:`avd_snapshot_delete`
  - :class:`SnapshotError`
  - :func:`make_snapshot_restore_setup_hook` — builds a
    :class:`~probe_gen.pipeline.gates.SetupHook` that restores a named
    snapshot before each gate run.

Pure subprocess wrappers; no side effects beyond the adb call.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from probe_gen.pipeline.gates import GateContext, SetupHook

# Maximum time we wait for any single adb-emu call. Snapshots can take
# longer on slow disks; tune via ``timeout`` parameter rather than this.
_DEFAULT_TIMEOUT = 120


class SnapshotError(RuntimeError):
    """Raised when an adb-emu snapshot command fails."""


@dataclass
class SnapshotInfo:
    name: str
    size_bytes: Optional[int]  # None if unknown
    created_iso: Optional[str]  # None if unknown


def _run_adb_emu(args: list[str], *, timeout: int = _DEFAULT_TIMEOUT) -> str:
    """Run ``adb emu <args>`` and return stdout, raising on nonzero exit.

    Concrete examples:
      _run_adb_emu(["avd", "snapshot", "save", "warm"])
      _run_adb_emu(["avd", "snapshot", "list"])
    """
    cmd = ["adb", "emu", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise SnapshotError(f"adb not on PATH: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SnapshotError(
            f"adb emu {' '.join(args)} timed out after {timeout}s"
        ) from exc
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise SnapshotError(
            f"adb emu {' '.join(args)} exit={proc.returncode}: {err or out}"
        )
    # adb emu uses stdout for diagnostic, "OK" terminator. Some commands
    # may use stderr too; concatenate so callers can grep.
    return out + ("\n" + err if err else "")


_SNAPSHOT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _validate_snapshot_name(name: str) -> None:
    if not name:
        raise SnapshotError("snapshot name is empty")
    if not _SNAPSHOT_NAME_RE.match(name):
        raise SnapshotError(
            f"snapshot name {name!r} contains invalid characters "
            "(only A-Z, a-z, 0-9, _, ., - allowed)"
        )


def avd_snapshot_save(name: str, *, timeout: int = 300) -> None:
    """Save the current emulator state as a named snapshot.

    Snapshot creation can take 10–60s depending on AVD size. The default
    timeout is generous (300s) to accommodate slow disks; override if
    you have a tighter SLO.
    """
    _validate_snapshot_name(name)
    _run_adb_emu(["avd", "snapshot", "save", name], timeout=timeout)


def avd_snapshot_load(name: str, *, timeout: int = 120) -> None:
    """Restore the emulator to the named snapshot.

    Restore is typically 5–15s but can be longer if RAM is large. The
    emulator must be running before this is called; otherwise ``adb emu``
    has nothing to talk to.
    """
    _validate_snapshot_name(name)
    _run_adb_emu(["avd", "snapshot", "load", name], timeout=timeout)


def avd_snapshot_delete(name: str, *, timeout: int = 60) -> None:
    """Delete a named snapshot from the AVD."""
    _validate_snapshot_name(name)
    _run_adb_emu(["avd", "snapshot", "del", name], timeout=timeout)


def avd_snapshot_list(*, timeout: int = 30) -> list[SnapshotInfo]:
    """Enumerate snapshots on the running emulator.

    The output of ``adb emu avd snapshot list`` is human-formatted and
    not stable across emulator versions; this parser extracts just the
    snapshot names. Size and timestamp columns are best-effort and may
    be ``None`` when unparseable.
    """
    out = _run_adb_emu(["avd", "snapshot", "list"], timeout=timeout)
    snapshots: list[SnapshotInfo] = []
    for raw_line in out.splitlines():
        line = raw_line.strip()
        # Skip header / footer / OK lines.
        if not line:
            continue
        lower = line.lower()
        if lower.startswith(("ok", "id ", "name ", "id\t", "name\t")):
            continue
        if "no snapshots" in lower:
            return []
        # Try a few common formats:
        #   <name>   <size>   <date>
        #   <id>     <name>   <size>   <date>
        parts = line.split()
        if not parts:
            continue
        # Two layouts in the wild:
        #   <name> <size> <date>           — newer emulator builds
        #   <id>   <name> <size> <date>    — older builds
        # If the first token is purely numeric, treat it as an id and use
        # the second token as the name. Otherwise the first token is the
        # name.
        first = parts[0]
        if first.isdigit() and len(parts) > 1:
            name = parts[1]
        else:
            name = first
        if not _SNAPSHOT_NAME_RE.match(name):
            # Couldn't parse — skip this line rather than fail the listing
            continue
        snapshots.append(SnapshotInfo(name=name, size_bytes=None, created_iso=None))
    return snapshots


def has_snapshot(name: str) -> bool:
    """Return True if a snapshot with the given name exists on the running emulator."""
    return any(s.name == name for s in avd_snapshot_list())


def make_snapshot_restore_setup_hook(
    snapshot_name: str,
    *,
    settle_seconds: float = 1.0,
) -> SetupHook:
    """Return a :class:`SetupHook` that restores a named AVD snapshot.

    The hook raises :class:`SnapshotError` (which the gate runner converts
    to ``GateOutcome.error``) if the snapshot is missing or restore fails.
    A small ``settle_seconds`` post-restore wait gives Android background
    services a moment to reattach before the probe runs. Default 1s; tune
    if probes are flaky on cold-restored states.
    """

    def hook(_ctx: GateContext) -> None:
        avd_snapshot_load(snapshot_name)
        if settle_seconds > 0:
            time.sleep(settle_seconds)

    return hook


__all__ = [
    "SnapshotError",
    "SnapshotInfo",
    "avd_snapshot_delete",
    "avd_snapshot_list",
    "avd_snapshot_load",
    "avd_snapshot_save",
    "has_snapshot",
    "make_snapshot_restore_setup_hook",
]
