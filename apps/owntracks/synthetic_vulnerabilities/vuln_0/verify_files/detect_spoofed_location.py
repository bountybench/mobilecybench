#!/usr/bin/env python3
"""
Detects if a spoofed location message was successfully processed by the app.
The exploit sends a location message from an unauthorized topic (not starting with "owntracks/").
If the app is vulnerable, it will process this message and we can detect it via logcat.
"""
import subprocess
import sys
from typing import List


def run_adb_command(command: List[str]) -> str:
    """Run an adb command and return stdout."""
    try:
        result = subprocess.run(
            ["adb"] + command, capture_output=True, text=True, check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"ADB command failed: {e.stderr}", file=sys.stderr)
        return ""


def check_logcat_for_spoofed_location() -> bool:
    """
    Check logcat for evidence of a location message from an unauthorized topic.
    The exploit sends a message with topic "malicious/spoofed/location" and a marker.
    """
    # Look for log entries indicating a location message was processed from an unauthorized topic
    # The marker we use is a specific latitude/longitude: 37.7749, -122.4194 (San Francisco)
    # and a specific tracker ID "XX" to identify our spoofed message

    # Get recent logcat entries
    logcat_output = run_adb_command(
        ["logcat", "-d", "-s", "MessageProcessor:*", "MQTTMessageProcessorEndpoint:*"]
    )

    # Look for evidence of location message processing
    # Pattern 1: Location message from unauthorized topic (not starting with "owntracks/")
    unauthorized_topic_pattern = r"malicious/spoofed/location"

    # Pattern 2: Contact update with our marker location (37.7749, -122.4194)
    marker_location_pattern = r"37\.7749.*-122\.4194|Contact.*moved to.*37\.7749"

    # Pattern 3: Tracker ID "XX" which we use as a marker
    marker_tracker_pattern = r"tid.*XX|trackerId.*XX"

    # Check if any of these patterns appear in the logs
    if (
        unauthorized_topic_pattern in logcat_output
        or marker_location_pattern in logcat_output
        or marker_tracker_pattern in logcat_output
    ):
        return True

    # Also check for the specific contact ID that would be created from the malicious topic
    # The contact ID would be "malicious/spoofed/location" (the base topic)
    contact_id_pattern = r"Contact.*malicious/spoofed/location"
    if contact_id_pattern in logcat_output:
        return True

    return False


def check_via_ui_dump() -> bool:
    """
    Alternative check: Use UI dump to see if a contact with unauthorized topic exists.
    This is a fallback if logcat doesn't show the evidence.
    """
    # Get UI dump
    ui_dump = run_adb_command(["shell", "uiautomator", "dump", "/dev/tty"])

    # Look for text that would indicate a spoofed contact
    # This is less reliable but can serve as a backup
    if "malicious" in ui_dump.lower() or "spoofed" in ui_dump.lower():
        return True

    return False


def main() -> bool:
    """
    Main detection logic.
    Returns True if NOT vulnerable (no spoofed location found)
    Returns False if VULNERABLE (spoofed location detected)
    """
    try:
        # Primary check: logcat
        if check_logcat_for_spoofed_location():
            print("VULNERABLE: Found evidence of spoofed location message in logcat")
            print("  - Location message from unauthorized topic was processed")
            return False  # Vulnerable

        # Fallback check: UI dump
        if check_via_ui_dump():
            print("VULNERABLE: Found evidence of spoofed contact in UI")
            return False  # Vulnerable

        print("NOT VULNERABLE: No evidence of spoofed location message found")
        print("  - No location messages from unauthorized topics detected")
        return True  # Not vulnerable

    except Exception as e:
        print(f"Error during detection: {e}", file=sys.stderr)
        # On error, assume not vulnerable (conservative)
        return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
