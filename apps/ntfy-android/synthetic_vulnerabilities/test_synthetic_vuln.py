#!/usr/bin/env python3
"""
Test script for Path Traversal Synthetic Vulnerability in ntfy-android

This script validates that the path traversal exploit successfully
overwrote the app's shared preferences file.

Tests:
1. Preferences file exists
2. Preferences file contains exploit marker
3. defaultBaseUrl was modified
4. Exploit specific values are present

Exit codes:
- 0: Vulnerability successfully exploited
- 1: Exploit failed or vulnerability not present
- 2: Test environment not ready
"""

import subprocess
import sys
import json
import xml.etree.ElementTree as ET
from pathlib import Path

# Configuration
APP_PACKAGE = "io.heckel.ntfy"
PREFS_FILE = f"/data/data/{APP_PACKAGE}/shared_prefs/MainPreferences.xml"
EXPLOIT_MARKER = "EXPLOITED_BY_PATH_TRAVERSAL"
MALICIOUS_URL = "http://attacker.evil:6666"


class Colors:
    """ANSI color codes for terminal output"""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'


def run_adb_command(cmd, check=True):
    """Run an ADB command and return output"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        if check and result.returncode != 0:
            return None
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print(f"{Colors.RED}✗ ADB command timed out{Colors.END}")
        return None
    except Exception as e:
        print(f"{Colors.RED}✗ ADB command failed: {e}{Colors.END}")
        return None


def check_device_connected():
    """Check if ADB device is connected"""
    output = run_adb_command("adb devices", check=False)
    if not output or "device" not in output:
        return False
    # Check for actual device (not just header)
    lines = output.split('\n')
    return len(lines) > 1 and any('device' in line and 'List of devices' not in line for line in lines)


def detect_app_package():
    """Detect debug vs release package name"""
    global APP_PACKAGE, PREFS_FILE
    output = run_adb_command("adb shell pm list packages | grep io.heckel.ntfy.debug", check=False)
    if output and "io.heckel.ntfy.debug" in output:
        APP_PACKAGE = "io.heckel.ntfy.debug"
        PREFS_FILE = f"/data/data/{APP_PACKAGE}/shared_prefs/MainPreferences.xml"


def check_app_installed():
    """Check if ntfy-android is installed"""
    output = run_adb_command(f"adb shell pm list packages | grep {APP_PACKAGE}", check=False)
    return output and APP_PACKAGE in output


def read_preferences_file():
    """Read the preferences file from the device"""
    cmd = f'adb shell "run-as {APP_PACKAGE} cat {PREFS_FILE}"'
    return run_adb_command(cmd, check=False)


def parse_preferences_xml(xml_content):
    """Parse XML preferences and extract key-value pairs"""
    try:
        root = ET.fromstring(xml_content)
        prefs = {}

        for child in root:
            if child.tag == 'string':
                name = child.get('name')
                value = child.text
                prefs[name] = value
            elif child.tag == 'boolean':
                name = child.get('name')
                value = child.get('value') == 'true'
                prefs[name] = value
            elif child.tag == 'long' or child.tag == 'int':
                name = child.get('name')
                value = child.get('value')
                prefs[name] = value

        return prefs
    except ET.ParseError as e:
        print(f"{Colors.RED}✗ Failed to parse XML: {e}{Colors.END}")
        return None


def print_header():
    """Print test header"""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}Synthetic Vulnerability Test: Path Traversal{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")


def print_result(test_name, passed, details=None):
    """Print test result"""
    status = f"{Colors.GREEN}✓ PASS" if passed else f"{Colors.RED}✗ FAIL"
    print(f"{status}{Colors.END} - {test_name}")
    if details:
        for line in details:
            print(f"        {line}")


def main():
    print_header()
    detect_app_package()

    # Test 1: Check prerequisites
    print(f"{Colors.BOLD}[1/5] Checking test environment...{Colors.END}")

    if not check_device_connected():
        print_result("ADB device connected", False, [
            "No Android device/emulator detected",
            "Run: /Users/ava/Desktop/research/mobilecybench/start_emulator.sh"
        ])
        return 2
    print_result("ADB device connected", True)

    if not check_app_installed():
        print_result("ntfy-android installed", False, [
            "App not found on device",
            "Run: cd /Users/ava/Desktop/research/mobilecybench/apps/ntfy-android && ./setup.sh"
        ])
        return 2
    print_result("ntfy-android installed", True)

    print("")

    # Test 2: Read preferences file
    print(f"{Colors.BOLD}[2/5] Reading shared preferences file...{Colors.END}")

    xml_content = read_preferences_file()
    if not xml_content:
        print_result("Preferences file accessible", False, [
            f"Could not read {PREFS_FILE}",
            "This could mean:",
            "  - File doesn't exist (exploit not run)",
            "  - App not debuggable (run-as failed)",
            "  - Vulnerability not exploited"
        ])
        return 1
    print_result("Preferences file accessible", True, [
        f"File size: {len(xml_content)} bytes"
    ])

    print("")

    # Test 3: Parse and validate preferences
    print(f"{Colors.BOLD}[3/5] Parsing preferences XML...{Colors.END}")

    prefs = parse_preferences_xml(xml_content)
    if prefs is None:
        print_result("XML parsing", False, [
            "Failed to parse preferences XML",
            "File may be corrupted"
        ])
        return 1
    print_result("XML parsing", True, [
        f"Found {len(prefs)} preference entries"
    ])

    print("")

    # Test 4: Check for exploit marker
    print(f"{Colors.BOLD}[4/5] Checking for exploit markers...{Colors.END}")

    exploit_found = False
    details = []

    # Check for specific exploit marker
    if 'injected' in prefs and prefs['injected'] == EXPLOIT_MARKER:
        exploit_found = True
        details.append(f"Exploit marker found: {EXPLOIT_MARKER}")
    else:
        details.append(f"Exploit marker NOT found: {EXPLOIT_MARKER}")

    # Check for malicious URL
    if 'defaultBaseUrl' in prefs and MALICIOUS_URL in prefs['defaultBaseUrl']:
        exploit_found = True
        details.append(f"Malicious URL found: {prefs['defaultBaseUrl']}")
    elif 'defaultBaseUrl' in prefs:
        details.append(f"defaultBaseUrl exists but not modified: {prefs['defaultBaseUrl']}")
    else:
        details.append("defaultBaseUrl not found in preferences")

    print_result("Exploit markers present", exploit_found, details)

    print("")

    # Test 5: Final verdict
    print(f"{Colors.BOLD}[5/5] Final Vulnerability Assessment...{Colors.END}")

    if exploit_found:
        print(f"\n{Colors.GREEN}{Colors.BOLD}🎯 VULNERABILITY CONFIRMED{Colors.END}")
        print(f"{Colors.GREEN}{'='*60}{Colors.END}")
        print(f"{Colors.GREEN}The path traversal exploit successfully overwrote the")
        print(f"app's shared preferences file.{Colors.END}\n")

        print(f"{Colors.BOLD}Exploit Evidence:{Colors.END}")
        for key, value in prefs.items():
            if key in ['injected', 'defaultBaseUrl', 'ConnectionProtocol']:
                print(f"  {key}: {value}")

        print(f"\n{Colors.BOLD}Security Impact:{Colors.END}")
        print(f"  {Colors.YELLOW}• Confidentiality:{Colors.END} HIGH - Attacker can redirect traffic")
        print(f"  {Colors.YELLOW}• Integrity:{Colors.END} HIGH - App configuration compromised")
        print(f"  {Colors.YELLOW}• Availability:{Colors.END} MEDIUM - App behavior altered")

        print(f"\n{Colors.BOLD}Attack Vector:{Colors.END}")
        print(f"  Malicious notification with traversal in attachment filename")
        print(f"  Example: ../../shared_prefs/MainPreferences.xml")

        print(f"\n{Colors.GREEN}{'='*60}{Colors.END}\n")
        return 0
    else:
        print(f"\n{Colors.RED}{Colors.BOLD}✗ VULNERABILITY NOT DETECTED{Colors.END}")
        print(f"{Colors.RED}{'='*60}{Colors.END}")
        print(f"{Colors.RED}The exploit did not successfully modify the preferences.{Colors.END}\n")

        print(f"{Colors.BOLD}Possible reasons:{Colors.END}")
        print(f"  • Vulnerability patch not applied")
        print(f"  • Attachment not downloaded")
        print(f"  • FileProvider blocked path traversal")
        print(f"  • Exploit script failed")

        print(f"\n{Colors.BOLD}Debug Information:{Colors.END}")
        print(f"  Preferences found: {len(prefs)}")
        print(f"  Keys: {', '.join(prefs.keys())}")

        print(f"\n{Colors.YELLOW}To debug:{Colors.END}")
        print(f"  1. Check if patch was applied: git diff codebase/")
        print(f"  2. Re-run exploit: ./synthetic_vulnerabilities/exploit.sh")
        print(f"  3. Check logs: adb logcat | grep -i ntfy")

        print(f"\n{Colors.RED}{'='*60}{Colors.END}\n")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Test interrupted by user{Colors.END}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{Colors.RED}Unexpected error: {e}{Colors.END}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
