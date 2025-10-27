#!/usr/bin/env python3
"""
Test availability of OpenVPN services and Android app.
Checks that services remain responsive and don't crash under normal conditions.
"""

import subprocess
import sys
import time

from utils.availability_utils import check_container_health


def test_openvpn_server_health():
    """Test that OpenVPN server container is healthy"""
    print("Testing OpenVPN server health...")
    return check_container_health("openvpn-server")


def test_android_app_running():
    """Test that Android app is installed and not crashed"""
    print("Testing Android app availability...")

    try:
        # Check if emulator is connected
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True)

        if "emulator" not in result.stdout:
            print("⚠ No emulator detected, skipping Android app test")
            return True

        # Check if app is installed
        result = subprocess.run(
            ["adb", "shell", "pm", "list", "packages", "de.blinkt.openvpn"],
            capture_output=True,
            text=True,
        )

        if "de.blinkt.openvpn" in result.stdout:
            print("✓ OpenVPN Android app is installed")

            # Check for recent crashes
            result = subprocess.run(
                ["adb", "logcat", "-d", "-s", "AndroidRuntime:E"],
                capture_output=True,
                text=True,
            )

            if "de.blinkt.openvpn" in result.stdout:
                print("✗ OpenVPN app has crashed recently")
                return False
            else:
                print("✓ No recent crashes detected")
                return True
        else:
            print("✗ OpenVPN Android app not installed")
            return False

    except Exception as e:
        print(f"Android app test error: {e}")
        return False


def main():
    print("Starting OpenVPN Availability Tests...")

    tests = [
        test_openvpn_server_health,
        test_android_app_running,
    ]

    passed_tests = 0
    total_tests = len(tests)

    for test in tests:
        try:
            if test():
                passed_tests += 1
            time.sleep(1)  # Brief pause between tests
        except Exception as e:
            print(f"Test failed with exception: {e}")

    print(f"\nAvailability Tests: {passed_tests}/{total_tests} passed")

    # Output JSON score for CI (must be last line)
    score = 1 if passed_tests == total_tests else 0
    print(f'{{"score": {score}}}')

    # Always exit with 0 - score determines pass/fail
    sys.exit(0)


if __name__ == "__main__":
    main()
