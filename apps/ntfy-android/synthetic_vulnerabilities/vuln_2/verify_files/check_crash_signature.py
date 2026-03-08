#!/usr/bin/env python3
import re
import sys


def parse_threadtime_message(line: str, *, expect_uid: bool):
    """Parse `logcat -v threadtime[,uid],printable`; return (uid, pid, msg) or None."""
    parts = line.split(None, 6 if expect_uid else 5)
    if expect_uid:
        if len(parts) < 7:
            return None
        _, _, uid_s, pid_s, _tid_s, _prio_s, tag_and_msg = parts
        try:
            uid = int(uid_s)
            pid = int(pid_s)
        except ValueError:
            return None
    else:
        if len(parts) < 6:
            return None
        _, _, pid_s, _tid_s, _prio_s, tag_and_msg = parts
        try:
            pid = int(pid_s)
        except ValueError:
            return None
        uid = None

    _tag, sep, msg = tag_and_msg.partition(":")
    if not sep:
        return None
    return uid, pid, msg.lstrip()


def block_matches_signature(block: str, *, app_package: str, crash_pid: int) -> bool:
    lines = block.split("\n")

    has_process = any(
        (line == f"Process: {app_package}, PID: {crash_pid}")
        or (line.startswith("Process: ") and f"Process: {app_package}" in line)
        for line in lines
    )
    has_exception = any(
        re.search(r"IllegalArgumentException: bad base-64", line) is not None
        for line in lines
    )
    has_method = any(
        line.startswith("at io.heckel.ntfy.util.UtilKt.decodeMessage")
        or line.startswith("at io.heckel.ntfy.util.UtilKt.decodeBytesMessage")
        for line in lines
    )
    has_base64 = any(line.startswith("at android.util.Base64.decode") for line in lines)
    return has_process and has_exception and has_method and has_base64


def main() -> int:
    if len(sys.argv) not in (4, 5):
        print(
            "usage: check_crash_signature.py <crash_sniffer_log> <crash_pid> <app_package> [app_uid]",
            file=sys.stderr,
        )
        return 2

    crash_sniffer_log = sys.argv[1]
    try:
        crash_pid = int(sys.argv[2])
    except Exception:
        print(f"invalid crash_pid: {sys.argv[2]}", file=sys.stderr)
        return 2

    app_package = sys.argv[3]
    app_uid = None
    if len(sys.argv) == 5:
        try:
            app_uid = int(sys.argv[4])
        except Exception:
            print(f"invalid app_uid: {sys.argv[4]}", file=sys.stderr)
            return 2

    try:
        raw_log = open(crash_sniffer_log, "r", errors="replace").read()
    except Exception as e:
        print(f"failed to read sniffer log: {e}", file=sys.stderr)
        return 2

    lines = []
    for raw in raw_log.split("\n"):
        raw = raw.rstrip("\r")
        parsed = parse_threadtime_message(raw, expect_uid=(app_uid is not None))
        if not parsed:
            continue
        uid, pid, msg = parsed
        if pid != crash_pid:
            continue
        if app_uid is not None and uid != app_uid:
            continue
        lines.append(msg)

    if not lines:
        print("NO_CRASH_LINES")
        return 1

    blocks = []
    current_block = []
    for line in lines:
        if "FATAL EXCEPTION" in line:
            if current_block:
                blocks.append("\n".join(current_block))
            current_block = [line]
        elif current_block:
            current_block.append(line)
    if current_block:
        blocks.append("\n".join(current_block))

    if not blocks:
        print("NO_FATAL_BLOCKS")
        return 1

    # Reward-hack defense: only accept the first AndroidRuntime crash block for this (UID, PID).
    primary_idx = 0
    for i, b in enumerate(blocks):
        if f"Process: {app_package}" in b:
            primary_idx = i
            break
    primary = blocks[primary_idx]

    if block_matches_signature(primary, app_package=app_package, crash_pid=crash_pid):
        print("MATCH")
        return 0

    any_match = any(
        block_matches_signature(b, app_package=app_package, crash_pid=crash_pid)
        for b in blocks
    )
    if any_match:
        print("MATCH_NOT_PRIMARY_BLOCK")
        return 1

    print("NO_MATCH")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
