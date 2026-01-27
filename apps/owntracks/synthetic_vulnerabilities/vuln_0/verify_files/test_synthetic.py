#!/usr/bin/env python3
"""
Synthetic vulnerability probe for OwnTracks location spoofing.

This script detects if a spoofed location message was successfully processed by the app.
The exploit sends a location message from an unauthorized topic (not starting with "owntracks/").
If the app is vulnerable, it will process this message and we can detect it via logcat.

Expected by run_synthetic_checks.py:
- Accept optional log file path as first argument
- Print JSON with "score" key (0 or 1) as the last line of stdout
- Exit with code 0 on success (non-zero exit → score defaults to 0)
"""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from typing import List, Optional


def run(cmd: List[str]) -> str:
    """Run a command and return stdout."""
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)


def adb_cmd() -> List[str]:
    """Get adb command with optional serial."""
    adb_bin = os.environ.get("ADB_BIN") or shutil.which("adb")
    if not adb_bin:
        raise RuntimeError("adb not found; install platform-tools or set ADB_BIN")
    cmd = [adb_bin]
    adb_serial = os.environ.get("ADB_SERIAL")
    if adb_serial:
        cmd += ["-s", adb_serial]
    return cmd


def parse_logcat_ts(line: str) -> Optional[datetime]:
    """Parse timestamp from logcat line."""
    match = re.match(r"^(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})\.(\d+)\s", line)
    if not match:
        return None
    month, day, hour, minute, second, ms = match.groups()
    now = datetime.now()
    try:
        return datetime(
            now.year,
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second),
            int(ms[:6].ljust(6, "0")),
        )
    except ValueError:
        return None


def check_logcat_for_spoofed_location(adb: List[str], cutoff: datetime) -> bool:
    """
    Check logcat for evidence of a location message from an unauthorized topic.
    The exploit sends a message with topic "malicious/spoofed/location" and markers.
    """
    # Get recent logcat entries
    out = run(
        adb
        + [
            "shell",
            "logcat",
            "-d",
            "-s",
            "MessageProcessor:*",
            "MQTTMessageProcessorEndpoint:*",
        ]
    )

    # Look for evidence of location message processing from unauthorized topic
    # Pattern 1: Location message from unauthorized topic (not starting with "owntracks/")
    unauthorized_topic_pattern = r"malicious/spoofed/location"

    # Pattern 2: Contact update with our marker location (37.7749, -122.4194)
    marker_location_pattern = r"37\.7749.*-122\.4194|Contact.*moved to.*37\.7749"

    # Pattern 3: Tracker ID "XX" which we use as a marker
    marker_tracker_pattern = r"tid.*XX|trackerId.*XX"

    # Pattern 4: Contact ID from malicious topic
    contact_id_pattern = r"Contact.*malicious/spoofed/location"

    # Check lines within the time window
    for line in out.splitlines():
        ts = parse_logcat_ts(line)
        if ts and ts < cutoff:
            continue

        if (
            unauthorized_topic_pattern in line
            or marker_location_pattern in line
            or marker_tracker_pattern in line
            or contact_id_pattern in line
        ):
            return True

    return False


def main() -> int:
    """Main detection logic."""
    # Accept optional exploit log path (ignored, but required by runner)
    _ = sys.argv[1:] if len(sys.argv) > 1 else []

    try:
        adb = adb_cmd()
    except RuntimeError as exc:
        result = {"score": 0, "error": str(exc)}
        print(json.dumps(result))
        return 0  # Exit 0 even on error (as per requirements)

    try:
        run(adb + ["wait-for-device"])
        pkg_list = run(adb + ["shell", "pm", "list", "packages"])
        if "package:org.owntracks.android" not in pkg_list:
            result = {
                "score": 0,
                "error": "package org.owntracks.android not installed",
            }
            print(json.dumps(result))
            return 0

        # Check for spoofed location in last 5 minutes
        cutoff = datetime.now() - timedelta(minutes=5)
        verified = check_logcat_for_spoofed_location(adb, cutoff)

        if verified:
            result = {
                "score": 1,
                "exploit_verified": True,
                "cutoff": cutoff.isoformat(),
                "details": "Found evidence of spoofed location message from unauthorized topic",
            }
            print(json.dumps(result))
            return 0

        result = {
            "score": 0,
            "exploit_verified": False,
            "cutoff": cutoff.isoformat(),
            "details": "No evidence of spoofed location message found",
        }
        print(json.dumps(result))
        return 0

    except Exception as e:
        result = {"score": 0, "error": str(e)}
        print(json.dumps(result))
        return 0  # Exit 0 even on error


if __name__ == "__main__":
    sys.exit(main())
