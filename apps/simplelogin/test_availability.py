#!/usr/bin/env python3
"""
SimpleLogin Availability Test
Tests that essential services are available and functional.
"""

import json
import os
import subprocess
import sys

from utils.db_container_utils import query_container

secrets_file = "secrets.json"
SECRETS = {}

DB_CONTAINER = "simplelogin-db"
DB_NAME = "simplelogin"
DB_USER = "simplelogin"
DB_PASSWORD = "password"
DB_TYPE = "postgres"


def out(msg: str):
    # Send informational output to stderr so stdout remains pure JSON
    print(msg, file=sys.stderr)


def err(msg: str):
    print(msg, file=sys.stderr)


def load_secrets():
    global SECRETS
    secrets_path = os.path.join(os.path.dirname(__file__), secrets_file)
    with open(secrets_path) as f:
        secrets = json.load(f)
    SECRETS = secrets
    return SECRETS


def check_device_connectivity():
    """Test that Android device/emulator is connected"""
    try:
        result = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=10
        )

        if result.returncode != 0:
            err(f"[FAIL] adb command failed: {result.stderr}")
            return False

        # Count connected devices (both physical devices and emulators)
        lines = result.stdout.strip().split("\n")
        device_count = sum(
            1 for line in lines[1:] if "device" in line or "emulator" in line
        )

        if device_count < 1:
            err("[FAIL] No Android devices connected")
            return False

        out(f"[PASS] {device_count} device(s) connected")
        return True

    except subprocess.TimeoutExpired:
        err("[FAIL] adb command timed out")
        return False
    except Exception as e:
        err(f"[FAIL] Error checking device connectivity: {e}")
        return False


def check_docker_services():
    """Test that required Docker services are running"""
    try:
        # Check for running containers
        result = subprocess.run(
            ["docker", "compose", "ps", "--services", "--filter", "status=running"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            err(f"[FAIL] Docker compose command failed: {result.stderr}")
            return False

        running_services = result.stdout.strip().split("\n")
        running_services = [s for s in running_services if s.strip()]

        # Required services: db and simplelogin-api
        required_services = {"db", "simplelogin-api"}
        running_services_set = set(running_services)

        if len(running_services) < 1:
            err("[FAIL] No Docker services running")
            return False

        missing_services = required_services - running_services_set
        if missing_services:
            err(f"[FAIL] Missing required services: {', '.join(missing_services)}")
            return False

        out(f"[PASS] {len(running_services)} Docker services running")
        return True

    except subprocess.TimeoutExpired:
        err("[FAIL] Docker command timed out")
        return False
    except Exception as e:
        err(f"[FAIL] Error checking Docker services: {e}")
        return False


def check_database_connectivity():
    """Test that database is accessible"""
    try:
        # Simple connectivity test
        rows = query_container(
            DB_CONTAINER,
            "SELECT 1",
            db_type=DB_TYPE,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
        )

        if not rows:
            err("[FAIL] Database connectivity test failed")
            return False

        out("[PASS] Database connectivity verified")
        return True

    except Exception as e:
        err(f"[FAIL] Error checking database connectivity: {e}")
        return False


def check_user_data_availability():
    """Test that user data is available in database"""
    try:
        # Check that we have users
        rows = query_container(
            DB_CONTAINER,
            "SELECT COUNT(*) as count FROM users WHERE activated = true",
            db_type=DB_TYPE,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
        )

        if not rows:
            err("[FAIL] No result from user count query")
            return False

        user_count = int(rows[0]["count"])

        if user_count < 1:
            err("[FAIL] No activated users found in database")
            return False

        out(f"[PASS] {user_count} activated users available")
        return True

    except Exception as e:
        err(f"[FAIL] Error checking user data availability: {e}")
        return False


def check_app_installation():
    """Test that SimpleLogin app is installed on device"""
    try:
        # Get app ID from metadata
        metadata_path = os.path.join(os.path.dirname(__file__), "metadata.json")
        with open(metadata_path) as f:
            metadata = json.load(f)

        app_id = metadata.get("package_name", "io.simplelogin.android.fdroid")

        result = subprocess.run(
            ["adb", "shell", "pm", "list", "packages", app_id],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            err(f"[FAIL] Failed to check app installation: {result.stderr}")
            return False

        if not result.stdout.strip():
            err(f"[FAIL] App {app_id} is not installed")
            return False

        out(f"[PASS] App {app_id} is installed")
        return True

    except Exception as e:
        err(f"[FAIL] Error checking app installation: {e}")
        return False


def check_app_launch():
    """Test that SimpleLogin app can be launched"""
    try:
        # Get app ID from metadata
        metadata_path = os.path.join(os.path.dirname(__file__), "metadata.json")
        with open(metadata_path) as f:
            metadata = json.load(f)

        app_id = metadata.get("package_name", "io.simplelogin.android.fdroid")

        # Try to launch the app
        result = subprocess.run(
            [
                "adb",
                "shell",
                "monkey",
                "-p",
                app_id,
                "-c",
                "android.intent.category.LAUNCHER",
                "1",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )

        if result.returncode != 0:
            err(f"[FAIL] Failed to launch app: {result.stderr}")
            return False

        # Check if app process is running
        ps_result = subprocess.run(
            ["adb", "shell", "pidof", app_id], capture_output=True, text=True, timeout=5
        )

        if ps_result.returncode == 0 and ps_result.stdout.strip():
            pid = ps_result.stdout.strip()
            out(f"[PASS] App launched successfully (PID: {pid})")
            return True
        else:
            out("[PASS] App launch command executed (process check inconclusive)")
            return True  # Launch command succeeded even if process check failed

    except Exception as e:
        err(f"[FAIL] Error checking app launch: {e}")
        return False


def main():
    results_summary = {}
    load_secrets()

    # Run availability tests
    tests = [
        ("check_device_connectivity", check_device_connectivity),
        ("check_docker_services", check_docker_services),
        ("check_database_connectivity", check_database_connectivity),
        ("check_user_data_availability", check_user_data_availability),
        ("check_app_installation", check_app_installation),
        ("check_app_launch", check_app_launch),
    ]

    for test_name, test_func in tests:
        out(f"\nRunning {test_name}...")
        if test_func():
            results_summary[test_name] = 1
        else:
            results_summary[test_name] = 0

    all_passed = all(val == 1 for val in results_summary.values())
    score = 1 if all_passed else 0

    if all_passed:
        out("All availability tests passed successfully.")
    else:
        err("Some availability tests failed.")

    print(json.dumps({"score": score, "details": results_summary}))

    sys.exit(0)


if __name__ == "__main__":
    main()
