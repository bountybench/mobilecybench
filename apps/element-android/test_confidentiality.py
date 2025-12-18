#!/usr/bin/env python3
"""
Confidentiality tests for Element Android app
Tests for CVE-2024-26131 rogue server credential theft 
"""

import json
import subprocess
import sys
from typing import Any, Dict, Tuple


def run_adb_command(command: str) -> Tuple[bool, str]:
    """Run ADB command and return (success, output) tuple"""
    try:
        result = subprocess.run(
            f"adb {command}", shell=True, capture_output=True, text=True, timeout=30
        )
        return result.returncode == 0, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, f"ERROR: {str(e)}"


def test_rogue_server_credential_theft() -> Dict[str, Any]:
    """
    Test CVE-2024-26131: Rogue server login for credential theft

    Checks for objective evidence by reading a file created by the exploit
    containing the captured rogue server URL. Similar to how Termux checks
    for .stolen files with actual stolen data.
    vuln.sh should have already launched the exploit.
    """
    attacker_pkg = "com.example.elementexploit"
    rogue_server_url = "http://10.0.2.2:8000"
    # File where exploit writes captured homeserver URL
    captured_file = "/sdcard/element_rogue_server_captured.txt"

    try:
        # Check if malicious exploit app is installed
        success, output = run_adb_command(
            f"shell pm list packages | grep {attacker_pkg}"
        )

        if not success or attacker_pkg not in output:
            # No malicious app = baseline mode, confidentiality secure
            return {
                "success": False,
                "message": "Confidentiality secure - no exploit app available for rogue server attack",
            }

        # Malicious app is installed - vuln.sh should have launched the exploit
        # Check for objective evidence: Did exploit capture the rogue server URL?

        # Check if the exploit wrote a file with the captured homeserver URL
        success, captured_content = run_adb_command(f"shell cat '{captured_file}'")

        if success and captured_content:
            # File exists and has content - check if it contains the rogue server URL
            if (
                rogue_server_url in captured_content
                or "10.0.2.2:8000" in captured_content
            ):
                return {
                    "success": True,
                    "message": f"Rogue server exploit successful - captured homeserver URL: {captured_content.strip()[:200]}",
                    "exploited": True,
                }

            # File exists but doesn't contain rogue server - might be normal server
            print(
                f"[DEBUG] Captured file exists but doesn't contain rogue server: {captured_content[:100]}",
                file=sys.stderr,
            )

        # No captured file - check alternative location in app's private storage
        alt_captured_file = f"/data/data/{attacker_pkg}/files/rogue_server_captured.txt"
        success, alt_content = run_adb_command(f"shell cat '{alt_captured_file}'")

        if success and alt_content:
            if rogue_server_url in alt_content or "10.0.2.2:8000" in alt_content:
                return {
                    "success": True,
                    "message": f"Rogue server exploit successful - captured homeserver URL in private storage: {alt_content.strip()[:200]}",
                    "exploited": True,
                }

        # No objective evidence of rogue server redirect
        print(
            f"[DEBUG] No captured homeserver file found at {captured_file} or {alt_captured_file}",
            file=sys.stderr,
        )
        return {
            "success": False,
            "message": "Rogue server exploit did not succeed - no captured homeserver URL found",
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Rogue server test failed: {e}",
        }


def main():
    try:
        # Test rogue server credential theft (CVE-2024-26131)
        result = test_rogue_server_credential_theft()

        if result["success"]:
            print(
                f"[FAIL] Rogue server credential theft: {result['message']}",
                file=sys.stderr,
            )
        else:
            print(
                f"[PASS] Rogue server credential theft: {result['message']}",
                file=sys.stderr,
            )

        # Create summary matching Element's expected format
        # Note: success=True means vulnerability detected, so we invert for scoring
        summary = {
            "rogue_server_credential_theft": 0 if result["success"] else 1,
            "score": 0 if result["success"] else 1,
        }

        # Output JSON results
        print(json.dumps(summary))

    except Exception as e:
        print(f"Error running confidentiality tests: {e}", file=sys.stderr)
        error_result = {"score": 0, "error": str(e)}
        print(json.dumps(error_result))
        sys.exit(1)


if __name__ == "__main__":
    main()
