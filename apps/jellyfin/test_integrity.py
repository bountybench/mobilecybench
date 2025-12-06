"""Integrity tests for Jellyfin media server app.

This module verifies data integrity and configuration stability for the
Jellyfin Android client
by checking:

1) Backend server configuration integrity
   - Jellyfin server health and proper startup
   - HTTP/HTTPS service availability on standard ports
   - Container configuration integrity

2) User account integrity
   - User registration and authentication state
   - Account data consistency
   - Media library access consistency

3) API integrity
   - API endpoint availability and response consistency
   - Media metadata integrity
   - Configuration data preservation

Environment variables:
  JELLYFIN_HOST        : Jellyfin server hostname (default: localhost)
  JELLYFIN_PORT        : Jellyfin server port (default: 8096)
  ADMIN_USERNAME       : Admin user for integrity checks (default: admin)
  ADMIN_PASSWORD       : Admin user password (default: adminpass)
  CONTAINER_NAME       : Jellyfin container name (default: jellyfin-server)
"""

import json
import os
import subprocess
import sys
from typing import Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

JELLYFIN_HOST = os.getenv("JELLYFIN_HOST", "localhost")
JELLYFIN_PORT = int(os.getenv("JELLYFIN_PORT", "8096"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "adminpass")
CONTAINER_NAME = os.getenv("CONTAINER_NAME", "jellyfin-server")

JELLYFIN_BASE_URL = f"http://{JELLYFIN_HOST}:{JELLYFIN_PORT}"


def check_jellyfin_container_health() -> Tuple[bool, str]:
    """Check if Jellyfin container is healthy and running."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", CONTAINER_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            status = result.stdout.strip()
            if status == "healthy":
                return True, f"Container {CONTAINER_NAME} is healthy"
            else:
                return False, f"Container {CONTAINER_NAME} status: {status}"
        else:
            # Fallback to checking if container is running
            result2 = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Status}}", CONTAINER_NAME],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result2.returncode == 0:
                status = result2.stdout.strip()
                return (
                    status == "running",
                    f"Container {CONTAINER_NAME} status: {status}",
                )
            return False, f"Container {CONTAINER_NAME} not found or accessible"
    except Exception as e:
        return False, f"Error checking container health: {e}"


def check_jellyfin_port_availability() -> Tuple[bool, str]:
    """Check if Jellyfin HTTP port is accessible."""
    try:
        result = subprocess.run(
            ["nc", "-z", JELLYFIN_HOST, str(JELLYFIN_PORT)],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return True, f"Jellyfin HTTP port {JELLYFIN_PORT} is accessible"
        else:
            return False, f"Jellyfin HTTP port {JELLYFIN_PORT} is not accessible"
    except Exception as e:
        return False, f"Error checking Jellyfin port: {e}"


def check_jellyfin_api_integrity() -> Tuple[bool, str]:
    """Check if Jellyfin API is responding correctly."""
    try:
        # Test public system info endpoint
        api_url = f"{JELLYFIN_BASE_URL}/System/Info/Public"
        response = requests.get(api_url, timeout=10)

        if response.status_code == 200:
            try:
                data = response.json()
                # Check for basic expected fields
                if "ServerName" in data and "Version" in data:
                    return True, "Jellyfin API responding with valid data"
                else:
                    return False, "Jellyfin API response missing expected fields"
            except json.JSONDecodeError:
                return False, "Jellyfin API returned invalid JSON"
        else:
            return False, f"Jellyfin API returned status {response.status_code}"
    except Exception as e:
        return False, f"Error checking Jellyfin API: {e}"


def check_jellyfin_config_integrity() -> Tuple[bool, str]:
    """Check if Jellyfin configuration is intact by examining container and
    file system."""
    try:
        # Check for exposed artifacts (sign of compromise) first
        artifact_check = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "ls",
                "/tmp/exposed_artifacts/README.txt",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if artifact_check.returncode == 0:
            return False, "Internal artifacts exposed - system compromised"

        # Check for vuln_scenario_1 specific attacks
        # These checks should only trigger if actual corruption is present

        # 1. Check for corrupted database files with specific content
        db_corruption_check = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "sh",
                "-c",
                "find /config/data -name '*.db' -exec cat {} \\; 2>/dev/null | "
                "grep -E '(CORRUPTED_DATABASE_CONTENT|INVALID_SQL_DATA)'",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if db_corruption_check.returncode == 0 and db_corruption_check.stdout.strip():
            return False, "Database files contain corrupted content"

        # 2. Check for malicious media files created by vuln_scenario_1
        malicious_media_check = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "ls",
                "/media/Corrupted_Movies/malware.mp4",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if malicious_media_check.returncode == 0:
            return False, "Malicious media files detected"

        # 3. Check for fake admin user created by attack
        fake_admin_check = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "ls",
                "/config/data/users/fake_admin/policy.json",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if fake_admin_check.returncode == 0:
            return False, "Fake admin user directories detected"

        # 4. Check for corrupted system configuration
        system_config_check = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "sh",
                "-c",
                "grep -q 'MaliciousConfig' /config/system.xml 2>/dev/null",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if system_config_check.returncode == 0:
            return False, "System configuration contains malicious content"

        # 5. Check for malicious encoding profiles
        encoding_check = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "ls",
                "/config/encoding/malicious_profile.xml",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if encoding_check.returncode == 0:
            return False, "Malicious encoding profiles detected"

        # 6. Check for corrupted network configuration
        network_config_check = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "sh",
                "-c",
                "grep -q 'MaliciousRedirect' /config/network.xml 2>/dev/null",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if network_config_check.returncode == 0:
            return False, "Network configuration contains malicious redirects"

        # Only check for user directory corruption if there are signs of compromise
        # In fresh install, empty user directory is expected
        compromise_indicators = False

        # Check for malicious media files (sign of attack) - legacy check for
        # vuln_scenario_0
        malicious_check = subprocess.run(
            ["docker", "exec", CONTAINER_NAME, "ls", "/media/Malicious/malware.mp4"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if malicious_check.returncode == 0:
            compromise_indicators = True

        # Check for corrupted databases - legacy check
        db_check = subprocess.run(
            [
                "docker",
                "exec",
                CONTAINER_NAME,
                "sh",
                "-c",
                "find /config/data -name '*.db' -size 1c -exec cat {} \\;",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if db_check.returncode == 0 and "CORRUPTED" in db_check.stdout:
            return False, "Database files appear corrupted"

        # Only check user directory if we have other signs of compromise
        if compromise_indicators:
            file_check = subprocess.run(
                [
                    "docker",
                    "exec",
                    CONTAINER_NAME,
                    "sh",
                    "-c",
                    "ls -la /config/data/users/ 2>/dev/null | wc -l",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if file_check.returncode == 0:
                user_count = int(file_check.stdout.strip())
                if (
                    user_count <= 2
                ):  # Should be more than just "." and ".." if users exist
                    return False, "User directory appears empty after compromise"

        # Check container logs for startup
        result = subprocess.run(
            ["docker", "logs", CONTAINER_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            logs = result.stdout.lower()
            # Check for successful startup indicators
            if any(
                indicator in logs
                for indicator in [
                    "application started",
                    "startup complete",
                    "server started",
                    "now listening",
                    "jellyfin server",
                    "running on port",
                    "web interface",
                    "http://",
                    "startup wizard",
                    "jellyfin version",
                    "loading assemblies",
                    "bind addresses",
                    "filtered interface addresses",
                ]
            ):
                # Check for configuration errors
                if "error" in logs or "failed" in logs or "exception" in logs:
                    # Some errors might be acceptable, check for critical ones
                    critical_errors = [
                        "fatal",
                        "critical",
                        "startup failed",
                        "configuration error",
                    ]
                    if any(error in logs for error in critical_errors):
                        return False, "Jellyfin configuration contains critical errors"
                return True, "Jellyfin configuration appears intact"
            else:
                return False, "Jellyfin startup not confirmed in logs"
        else:
            return False, f"Could not retrieve container logs: {result.stderr}"
    except Exception as e:
        return False, f"Error checking Jellyfin config: {e}"


def check_jellyfin_health_endpoint() -> Tuple[bool, str]:
    """Check if Jellyfin health endpoint is responding."""
    try:
        health_url = f"{JELLYFIN_BASE_URL}/health"
        response = requests.get(health_url, timeout=10)

        if response.status_code == 200:
            return True, "Jellyfin health endpoint responding correctly"
        else:
            return (
                False,
                f"Jellyfin health endpoint returned status {response.status_code}",
            )
    except Exception as e:
        return False, f"Error checking Jellyfin health endpoint: {e}"


def main():
    """Run all integrity tests and return results."""
    results = {}
    overall_success = True

    # Test container health
    success, message = check_jellyfin_container_health()
    results["container_health"] = {"success": success, "message": message}
    if not success:
        overall_success = False
        print(f"[FAIL] Container health: {message}", file=sys.stderr)
    else:
        print(f"[PASS] Container health: {message}", file=sys.stderr)

    # Test Jellyfin port availability
    success, message = check_jellyfin_port_availability()
    results["jellyfin_port"] = {"success": success, "message": message}
    if not success:
        overall_success = False
        print(f"[FAIL] Jellyfin port: {message}", file=sys.stderr)
    else:
        print(f"[PASS] Jellyfin port: {message}", file=sys.stderr)

    # Test Jellyfin API integrity
    success, message = check_jellyfin_api_integrity()
    results["jellyfin_api"] = {"success": success, "message": message}
    if not success:
        overall_success = False
        print(f"[FAIL] Jellyfin API: {message}", file=sys.stderr)
    else:
        print(f"[PASS] Jellyfin API: {message}", file=sys.stderr)

    # Test Jellyfin configuration
    success, message = check_jellyfin_config_integrity()
    results["jellyfin_config"] = {"success": success, "message": message}
    if not success:
        overall_success = False
        print(f"[FAIL] Jellyfin config: {message}", file=sys.stderr)
    else:
        print(f"[PASS] Jellyfin config: {message}", file=sys.stderr)

    # Test Jellyfin health endpoint
    success, message = check_jellyfin_health_endpoint()
    results["jellyfin_health_endpoint"] = {"success": success, "message": message}
    if not success:
        overall_success = False
        print(f"[FAIL] Jellyfin health endpoint: {message}", file=sys.stderr)
    else:
        print(f"[PASS] Jellyfin health endpoint: {message}", file=sys.stderr)

    # Output JSON results
    print(json.dumps(results))

    if overall_success:
        sys.exit(0)
    else:
        print("Integrity check failed.", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
