#!/usr/bin/env python3
"""CLI for emulator lifecycle: start, stop, status, list."""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from utils.emulator_manager import EmulatorManager

PROJECT_ROOT = Path(__file__).parent
DEFAULT_SDK = "35"
DEFAULT_ANDROID_HOME = str(Path.home() / ".android-sdk")


def _adb(*args: str, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["adb", *args], capture_output=True, text=True, timeout=timeout
    )


def _discover_emulators() -> list[str]:
    """Return running emulator device IDs via `adb devices`.

    Uses raw adb rather than EmulatorManager because stop/status/list operate on
    emulators we didn't start (stale, from other tools).
    """
    result = _adb("devices")
    if result.returncode != 0:
        raise RuntimeError(f"adb devices failed: {result.stderr.strip()}")
    return [
        parts[0]
        for line in result.stdout.splitlines()[1:]
        if (parts := line.split("\t"))
        and len(parts) == 2
        and parts[0].startswith("emulator-")
    ]


def _stop_and_wait(device_ids: list[str]) -> None:
    """Kill emulators and wait for them to disappear from adb."""
    for device_id in device_ids:
        print(f"Stopping {device_id}...")
        _adb("-s", device_id, "emu", "kill")
        for _ in range(30):
            if device_id not in _discover_emulators():
                break
            time.sleep(1)
        else:
            raise RuntimeError(f"Timeout waiting for {device_id} to stop")
        print(f"Stopped {device_id}")


def cmd_start(args: argparse.Namespace) -> int:
    """Start emulator. Refuses if one is already running (single-emulator policy)."""
    try:
        os.environ.setdefault("ANDROID_HOME", DEFAULT_ANDROID_HOME)
        running = _discover_emulators()
        if running:
            print(
                f"Error: emulator already running ({running[0]}). Run ./stop_emulator.sh first."
            )
            return 1

        print(f"Starting emulator (SDK {args.sdk})...")
        display = "headless" if args.headless else "headed"
        manager = EmulatorManager(
            project_root=PROJECT_ROOT,
            sdk_version=args.sdk,
            rootable=True,
            emulator_display=display,
            emulator_backend="native",
        )
        try:
            manager.start_in_background()
            manager.wait_until_ready(timeout=300)
        except Exception:
            try:
                manager.stop()
            except RuntimeError as cleanup_error:
                print(
                    f"Warning: emulator cleanup failed after startup error: {cleanup_error}",
                    file=sys.stderr,
                )
            raise
        print(f"Emulator ready: {manager.device_id}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}")
        return 1


def cmd_stop(_args: argparse.Namespace) -> int:
    """Stop all running emulators."""
    from utils.emulator_manager import _reap_emulator_pidfile

    try:
        running = _discover_emulators()
        if running:
            if len(running) > 1:
                print(
                    f"Warning: we only support one emulator at a time; but {len(running)} emulators are currently running, stopping all"
                )
            _stop_and_wait(running)
        else:
            print("No running emulators found via adb")

        # Whether or not adb saw a device, reap any pidfile-tracked qemu
        # orphan from a prior crashed run. Only kills the PID we
        # recorded ourselves; if the pidfile is absent or stale this is a
        # no-op.
        _reap_emulator_pidfile(PROJECT_ROOT)
        return 0
    except Exception as exc:
        print(f"Error: {exc}")
        return 1


def cmd_status(_args: argparse.Namespace) -> int:
    """Show running emulators and boot state."""
    try:
        running = _discover_emulators()
        if not running:
            print("No emulators running.")
            return 0
        for device_id in running:
            boot = _adb(
                "-s", device_id, "shell", "getprop", "sys.boot_completed", timeout=5
            )
            state = "booted" if boot.stdout.strip() == "1" else "booting"
            print(f"  {device_id}  {state}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}")
        return 1


def cmd_list(_args: argparse.Namespace) -> int:
    """List available rootable AVDs."""
    try:
        android_home = os.environ.get("ANDROID_HOME", DEFAULT_ANDROID_HOME)
        emulator_bin = Path(android_home) / "emulator" / "emulator"
        if not emulator_bin.exists():
            print(f"Error: emulator not found at {emulator_bin}. Run ./setup.sh first.")
            return 1
        result = subprocess.run(
            [str(emulator_bin), "-list-avds"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for avd in result.stdout.splitlines():
            if avd.strip().endswith("_google_apis"):
                print(f"  {avd.strip()}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Android Emulator Management")
    sub = parser.add_subparsers(dest="command")

    start_p = sub.add_parser("start", help="Start emulator and wait for boot")
    start_p.add_argument(
        "--sdk", default=DEFAULT_SDK, help=f"SDK version (default: {DEFAULT_SDK})"
    )
    start_p.add_argument(
        "--headless", action="store_true", help="Run without display window"
    )
    start_p.set_defaults(handler=cmd_start)

    sub.add_parser("stop", help="Stop running emulator(s)").set_defaults(
        handler=cmd_stop
    )
    sub.add_parser("status", help="Show running emulators").set_defaults(
        handler=cmd_status
    )
    sub.add_parser("list", help="List available AVDs").set_defaults(handler=cmd_list)

    args = parser.parse_args()
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
