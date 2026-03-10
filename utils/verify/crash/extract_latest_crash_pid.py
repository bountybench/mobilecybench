#!/usr/bin/env python3
"""Extract the PID of the most recent APP CRASH from `dumpsys activity exit-info`.

Reads exit-info text from stdin; prints the PID of the latest crash for the
given package that occurred after the baseline epoch.

Usage:
    adb shell dumpsys activity exit-info <pkg> \
        | python3 extract_latest_crash_pid.py <baseline_epoch> <tz_offset> <app_package>

Exit codes:
    0 - found a crash; PID printed to stdout
    1 - no qualifying crash found
    2 - usage / parse error
"""
import re
import sys
from datetime import datetime, timedelta, timezone


def parse_tz_offset(tz_offset: str) -> timezone:
    if not re.match(r"^[+-][0-9]{4}$", tz_offset):
        raise ValueError(f"invalid tz offset: {tz_offset}")
    sign = 1 if tz_offset.startswith("+") else -1
    hours = int(tz_offset[1:3])
    mins = int(tz_offset[3:5])
    return timezone(sign * timedelta(hours=hours, minutes=mins))


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "usage: extract_latest_crash_pid.py <baseline_epoch> <tz_offset> <app_package>",
            file=sys.stderr,
        )
        return 2

    try:
        baseline_device_epoch = int(sys.argv[1])
    except Exception:
        print(f"invalid baseline epoch: {sys.argv[1]}", file=sys.stderr)
        return 2

    tz_offset = sys.argv[2]
    app_package = sys.argv[3]

    try:
        tz = parse_tz_offset(tz_offset)
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 2

    ts_re = re.compile(
        r"timestamp=(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+) pid=(\d+)"
    )
    proc_re = re.compile(r"process=([^\s]+)\s+reason=\d+\s+\(([^)]+)\)")

    current_ts = None
    current_pid = None
    best_epoch = None
    best_pid = None

    for line in sys.stdin.read().split("\n"):
        line = line.rstrip("\r")
        m = ts_re.search(line)
        if m:
            current_ts = m.group(1)
            current_pid = m.group(2)
            continue

        m = proc_re.search(line)
        if not m or current_ts is None or current_pid is None:
            continue

        proc = m.group(1)
        reason_text = m.group(2)
        if proc != app_package:
            continue
        if "APP CRASH" not in reason_text:
            continue

        try:
            dt = datetime.strptime(current_ts, "%Y-%m-%d %H:%M:%S.%f").replace(
                tzinfo=tz
            )
            epoch = int(dt.timestamp())
        except Exception:
            continue

        # Ignore stale crash events (allow 5s skew).
        if epoch < baseline_device_epoch - 5:
            continue

        if best_epoch is None or epoch > best_epoch:
            best_epoch = epoch
            best_pid = current_pid

    if best_pid is None:
        return 1

    print(best_pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
