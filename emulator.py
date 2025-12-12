#!/usr/bin/env python3

import argparse
import subprocess
import sys
from pathlib import Path

from utils.emulator_manager import EmulatorManager
from utils.logger import logger


def list_avds():
    try:
        android_home = Path.home() / ".android-sdk"
        emulator_bin = android_home / "emulator" / "emulator"
        if not emulator_bin.exists():
            logger.error(f"Emulator binary not found at {emulator_bin}")
            logger.error("Please run ./setup.sh first")
            return 1
        result = subprocess.run(
            [str(emulator_bin), "-list-avds"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.error("Failed to list AVDs")
            return 1

        avds = [
            line.strip() for line in result.stdout.strip().split("\n") if line.strip()
        ]
        if not avds:
            logger.info("No AVDs found. Run ./setup.sh to create them.")
            return 0
        logger.info("Available AVDs:")
        for avd in avds:
            if "google_apis_playstore" in avd:
                avd_type = "non-rootable"
            elif "google_apis" in avd:
                avd_type = "rootable"
            else:
                avd_type = "unknown"
            logger.info(f"  • {avd} ({avd_type})")
        return 0

    except Exception as e:
        logger.error(f"Error listing AVDs: {e}")
        return 1


def start_emulator(sdk_version: str, rootable: bool = True):
    # note: starting two emulators with same SDK version is not supported
    # different sdk versions are okay
    try:
        image_type = "rootable" if rootable else "non-rootable"

        logger.info(f"Starting {image_type} emulator (SDK {sdk_version})...")

        with EmulatorManager(
            docker_mode=False,
            project_root=Path(__file__).parent,
            sdk_version=sdk_version,
            rootable=rootable,
        ) as manager:
            manager.start_in_background()
            manager.wait_until_ready(timeout=300)

            logger.info("=" * 60)
            logger.info(f"Emulator ready! Device ID: {manager.device_id}")
            logger.info("=" * 60)

            if rootable:
                logger.info("You can now use 'adb root' to get root access")
            logger.info("\nPress Ctrl+C to stop the emulator...")

            try:
                # Keep running until user interrupts
                import signal
                signal.pause()
            except KeyboardInterrupt:
                logger.info("\nStopping emulator...")
        return 0

    except Exception as e:
        logger.error(f"Failed to start emulator: {e}")
        return 1


def stop_emulator():
    try:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            logger.error("Failed to check running emulators")
            return 1
        lines = result.stdout.strip().split("\n")[1:]  # Skip header
        emulators = []

        for line in lines:
            if line.strip() and "\t" in line:
                device_id = line.split("\t")[0].strip()
                if device_id.startswith("emulator-"):
                    emulators.append(device_id)
        if not emulators:
            logger.info("No running emulators found")
            return 0

        # If only one emulator, stop it directly
        if len(emulators) == 1:
            device_id = emulators[0]
            logger.info(f"Stopping {device_id}...")
            subprocess.run(
                ["adb", "-s", device_id, "emu", "kill"],
                capture_output=True,
                timeout=10,
            )
            logger.info(f"Stopped {device_id}")
            return 0

        # Multiple emulators - let user choose
        logger.info(f"Found {len(emulators)} running emulators:")
        for i, device_id in enumerate(emulators, 1):
            print(f"  {i}. {device_id}")
        print(f"  {len(emulators) + 1}. Stop all")
        print("  0. Cancel")

        try:
            choice = int(input("\nSelect emulator to stop: ").strip())

            if choice == 0:
                logger.info("Cancelled")
                return 0
            elif 1 <= choice <= len(emulators):
                device_id = emulators[choice - 1]
                logger.info(f"Stopping {device_id}...")
                subprocess.run(
                    ["adb", "-s", device_id, "emu", "kill"],
                    capture_output=True,
                    timeout=10,
                )
                logger.info(f"Stopped {device_id}")
                return 0
            elif choice == len(emulators) + 1:
                logger.info("Stopping all emulators...")
                for device_id in emulators:
                    logger.info(f"Stopping {device_id}...")
                    subprocess.run(
                        ["adb", "-s", device_id, "emu", "kill"],
                        capture_output=True,
                        timeout=10,
                    )
                logger.info(f"Stopped {len(emulators)} emulator(s)")
                return 0
            else:
                logger.error("Invalid selection")
                return 1

        except ValueError:
            logger.error("Invalid input. Please enter a number.")
            return 1
        except KeyboardInterrupt:
            print()
            logger.info("Cancelled")
            return 0

    except FileNotFoundError:
        logger.error("adb not found. Make sure ANDROID_HOME is set correctly.")
        return 1
    except Exception as e:
        logger.error(f"Error stopping emulators: {e}")
        return 1


def status():
    try:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.error("Failed to check emulator status")
            return 1
        logger.info("Running devices:")
        print(result.stdout)

        # Check if any emulators are running
        lines = result.stdout.strip().split("\n")[1:]  # Skip header
        emulator_count = sum(
            1 for line in lines if "emulator-" in line and "device" in line
        )
        if emulator_count == 0:
            logger.info(
                "\nNo emulators running. Use 'python emulator.py start' to start one."
            )
        else:
            logger.info(f"\n{emulator_count} emulator(s) running")
        return 0

    except FileNotFoundError:
        logger.error("adb not found. Make sure ANDROID_HOME is set correctly.")
        return 1
    except Exception as e:
        logger.error(f"Error checking status: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Android Emulator Management Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s list                           # List all available AVDs
  %(prog)s start --sdk 35                 # Start rootable emulator (SDK 35, default)
  %(prog)s start --sdk 35 --no-rootable   # Start non-rootable emulator (SDK 35)
  %(prog)s status                         # Show running emulators
  %(prog)s stop                           # Stop all running emulators
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    subparsers.add_parser("list", help="List all available AVDs")
    start_parser = subparsers.add_parser("start", help="Start an emulator")
    start_parser.add_argument(
        "--sdk",
        type=str,
        default="35",
        help="Android SDK version (default: 35)",
    )
    start_parser.add_argument(
        "--rootable",
        action="store_true",
        default=True,
        dest="rootable",
        help="Use rootable emulator (default)",
    )
    start_parser.add_argument(
        "--no-rootable",
        action="store_false",
        dest="rootable",
        help="Use non-rootable emulator (production-like)",
    )
    subparsers.add_parser("stop", help="Stop all running emulators")
    subparsers.add_parser("status", help="Show status of running emulators")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    if args.command == "list":
        return list_avds()
    elif args.command == "start":
        return start_emulator(args.sdk, args.rootable)
    elif args.command == "stop":
        return stop_emulator()
    elif args.command == "status":
        return status()
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
