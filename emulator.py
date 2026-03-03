#!/usr/bin/env python3
"""CLI for emulator lifecycle: start, stop, status, list.

All commands route through EmulatorManager for consistent behavior.
Use ./start_emulator.sh, ./stop_emulator.sh, ./check_device.sh as shortcuts.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from utils.emulator_manager import EmulatorManager, EmulatorState


def _discover_emulators() -> list[str]:
    """Discover running emulator device IDs via adb devices."""
    result = subprocess.run(
        ["adb", "devices"], capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        raise RuntimeError("Failed to check running emulators")
    emulators = []
    for line in result.stdout.strip().split("\n")[1:]:
        if line.strip() and "\t" in line:
            device_id = line.split("\t")[0].strip()
            if device_id.startswith("emulator-"):
                emulators.append(device_id)
    return emulators


def _make_manager_for_device(device_id: str) -> EmulatorManager:
    """Create an EmulatorManager attached to an already-running device."""
    if not os.getenv("ANDROID_HOME"):
        os.environ["ANDROID_HOME"] = str(Path.home() / ".android-sdk")
    manager = EmulatorManager(
        project_root=Path(__file__).parent,
        sdk_version=os.getenv("ANDROID_SDK_VERSION", "35"),
        rootable=True,
        emulator_display="headed",
        emulator_backend="native",
    )
    manager.device_id = device_id
    manager.state = EmulatorState.RUNNING
    return manager


def cmd_start(args):
    """Start emulator, wait for boot, return. 
    Reuses existing emulator if one is running. (old local CI behavior)"""
    try:
        existing = _discover_emulators()
        if existing:
            print(f"Emulator already running: {existing[0]}")
            return 0

        print(f"Starting emulator (SDK {args.sdk})...")
        manager = EmulatorManager(
            project_root=Path(__file__).parent,
            sdk_version=args.sdk,
            rootable=True,
            emulator_display="headed",
            emulator_backend="native",
        )
        manager.start_in_background()
        manager.wait_until_ready(timeout=300)
        print(f"Emulator ready: {manager.device_id}")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_stop(_args):
    """Stop running emulator(s)."""
    try:
        emulators = _discover_emulators()
        if not emulators:
            print("No running emulators found")
            return 0

        if len(emulators) == 1:
            print(f"Stopping {emulators[0]}...")
            _make_manager_for_device(emulators[0]).stop()
            print(f"Stopped {emulators[0]}")
            return 0

        # Multiple emulators — let user choose
        print(f"Found {len(emulators)} running emulators:")
        for i, device_id in enumerate(emulators, 1):
            print(f"  {i}. {device_id}")
        print(f"  {len(emulators) + 1}. Stop all")
        print("  0. Cancel")

        try:
            choice = int(input("\nSelect emulator to stop: ").strip())
            if choice == 0:
                return 0
            elif 1 <= choice <= len(emulators):
                device_id = emulators[choice - 1]
                print(f"Stopping {device_id}...")
                _make_manager_for_device(device_id).stop()
                print(f"Stopped {device_id}")
                return 0
            elif choice == len(emulators) + 1:
                for device_id in emulators:
                    print(f"Stopping {device_id}...")
                    _make_manager_for_device(device_id).stop()
                print(f"Stopped {len(emulators)} emulator(s)")
                return 0
            else:
                print("Invalid selection")
                return 1
        except ValueError:
            print("Invalid input. Please enter a number.")
            return 1
        except KeyboardInterrupt:
            print("\nCancelled")
            return 0

    except FileNotFoundError:
        print("Error: adb not found. Make sure ANDROID_HOME is set correctly.")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_status(_args):
    """Show running emulators and boot state."""
    try:
        emulators = _discover_emulators()
        if not emulators:
            print("No emulators running.")
            return 0
        for device_id in emulators:
            boot = subprocess.run(
                ["adb", "-s", device_id, "shell", "getprop", "sys.boot_completed"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            print(f"  {device_id}  {'booted' if boot == '1' else 'booting'}")
        return 0
    except FileNotFoundError:
        print("Error: adb not found. Make sure ANDROID_HOME is set correctly.")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        return 1


def cmd_list(_args):
    """List available AVDs."""
    try:
        android_home = os.getenv("ANDROID_HOME", str(Path.home() / ".android-sdk"))
        emulator_bin = Path(android_home) / "emulator" / "emulator"
        if not emulator_bin.exists():
            print(f"Error: Emulator not found at {emulator_bin}. Run ./setup.sh first.")
            return 1
        result = subprocess.run(
            [str(emulator_bin), "-list-avds"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            print("Error: Failed to list AVDs")
            return 1
        avds = [
            line.strip() for line in result.stdout.strip().split("\n") if line.strip()
        ]
        if not avds:
            print("No AVDs found. Run ./setup.sh to create them.")
            return 0
        for avd in avds:
            if "google_apis_playstore" in avd:
                kind = "non-rootable"
            elif "google_apis" in avd:
                kind = "rootable"
            else:
                kind = "unknown"
            print(f"  {avd} ({kind})")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Android Emulator Management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s start              # Start emulator (SDK 35, waits for boot)
  %(prog)s start --sdk 34     # Start emulator with SDK 34
  %(prog)s stop               # Stop running emulator(s)
  %(prog)s status             # Show running emulators
  %(prog)s list               # List available AVDs
        """,
    )
    sub = parser.add_subparsers(dest="command")

    sp_start = sub.add_parser("start", help="Start emulator and wait for boot")
    sp_start.add_argument(
        "--sdk", default="35", help="Android SDK version (default: 35)"
    )

    sub.add_parser("stop", help="Stop running emulator(s)")
    sub.add_parser("status", help="Show running emulators")
    sub.add_parser("list", help="List available AVDs")

    args = parser.parse_args()
    cmds = {
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "list": cmd_list,
    }
    if args.command in cmds:
        return cmds[args.command](args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
