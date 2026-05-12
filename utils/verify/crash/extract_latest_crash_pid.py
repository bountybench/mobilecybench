#!/usr/bin/env python3
"""Extract APP CRASH PIDs from `dumpsys activity exit-info`.

Reads exit-info text from stdin; by default prints the PID of the latest crash
for the given package that occurred after the baseline epoch.  With ``--all``,
prints all qualifying PIDs in newest-first order.

Usage:
    adb shell dumpsys activity exit-info <pkg> \
        | python3 extract_latest_crash_pid.py <baseline_epoch> <tz_offset> <app_package>
    adb shell dumpsys activity exit-info <pkg> \
        | python3 extract_latest_crash_pid.py --all <baseline_epoch> <tz_offset> <app_package>

Exit codes:
    0 - found crash(es); PID(s) printed to stdout
    1 - no qualifying crash found
    2 - usage / parse error
"""
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class CrashExitInfo:
    """Parsed APP CRASH entry from ``dumpsys activity exit-info``."""

    timestamp: datetime
    pid: str
    order: int


def parse_tz_offset(tz_offset: str) -> timezone:
    if not re.match(r"^[+-][0-9]{4}$", tz_offset):
        raise ValueError(f"invalid tz offset: {tz_offset}")
    sign = 1 if tz_offset.startswith("+") else -1
    hours = int(tz_offset[1:3])
    mins = int(tz_offset[3:5])
    return timezone(sign * timedelta(hours=hours, minutes=mins))


def extract_crash_entries(
    text: str, baseline_epoch: int, tz: timezone, app_package: str
) -> "list[CrashExitInfo]":
    """Return APP CRASH entries after *baseline_epoch* newest-first.

    The 5s skew allowance matches the historic ``extract_crash_pid`` behavior.
    PIDs are de-duplicated after sorting so a process is checked only once even
    if ``exit-info`` repeats it.
    """
    ts_re = re.compile(
        r"timestamp=(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+) pid=(\d+)"
    )
    proc_re = re.compile(r"process=([^\s]+)\s+reason=\d+\s+\(([^)]+)\)")

    current_ts: "str | None" = None
    current_pid: "str | None" = None
    entries: "list[CrashExitInfo]" = []

    for order, line in enumerate(text.split("\n")):
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
        except Exception as exc:
            print(
                f"warning: unparseable timestamp '{current_ts}': {exc}",
                file=sys.stderr,
            )
            continue

        # Ignore stale crash events (allow 5s skew).
        if dt.timestamp() < baseline_epoch - 5:
            continue

        entries.append(CrashExitInfo(timestamp=dt, pid=current_pid, order=order))

    entries.sort(key=lambda entry: (entry.timestamp, entry.order), reverse=True)

    seen_pids = set()
    deduped = []
    for entry in entries:
        if entry.pid in seen_pids:
            continue
        seen_pids.add(entry.pid)
        deduped.append(entry)
    return deduped


def extract_crash_pids(
    text: str, baseline_epoch: int, tz: timezone, app_package: str
) -> "list[str]":
    """Return qualifying APP CRASH PIDs newest-first."""

    return [
        entry.pid
        for entry in extract_crash_entries(text, baseline_epoch, tz, app_package)
    ]


def extract_crash_pid(
    text: str, baseline_epoch: int, tz: timezone, app_package: str
) -> "str | None":
    """Return the latest qualifying APP CRASH PID, or ``None``."""

    pids = extract_crash_pids(text, baseline_epoch, tz, app_package)
    return pids[0] if pids else None


def main() -> int:
    emit_all = False
    args = sys.argv[1:]
    if args and args[0] == "--all":
        emit_all = True
        args = args[1:]

    if len(args) != 3:
        print(
            "usage: extract_latest_crash_pid.py [--all] <baseline_epoch> <tz_offset> <app_package>",
            file=sys.stderr,
        )
        return 2

    try:
        baseline_epoch = int(args[0])
    except Exception:
        print(f"invalid baseline epoch: {args[0]}", file=sys.stderr)
        return 2

    try:
        tz = parse_tz_offset(args[1])
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 2

    pids = extract_crash_pids(sys.stdin.read(), baseline_epoch, tz, args[2])
    if not pids:
        return 1

    if emit_all:
        print("\n".join(pids))
    else:
        print(pids[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
