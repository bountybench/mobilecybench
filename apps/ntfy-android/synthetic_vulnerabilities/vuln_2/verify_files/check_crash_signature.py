#!/usr/bin/env python3
import re
import sys


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "usage: check_crash_signature.py <crash_sniffer_log> <crash_pid> <app_package>",
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

    try:
        raw_log = open(crash_sniffer_log, "r", errors="replace").read()
    except Exception as e:
        print(f"failed to read sniffer log: {e}", file=sys.stderr)
        return 2

    pid_line_re = re.compile(
        r"^\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\s+(\d+)\s+\d+\s+[A-Z]\s+[^:]+:\s?(.*)$"
    )

    lines = []
    for raw in raw_log.split("\n"):
        raw = raw.rstrip("\r")
        m = pid_line_re.match(raw)
        if not m:
            continue
        pid = int(m.group(1))
        if pid != crash_pid:
            continue
        lines.append(m.group(2))

    if not lines:
        print("NO_CRASH_LINES")
        return 1

    # ── am crash detection ────────────────────────────────────────────────
    # If ANY line for this PID contains CrashedByAdbException, the crash was
    # triggered by 'am crash', not a real vulnerability exploit. The sniffer
    # captures this even if the agent later clears the crash ring buffer.
    for line in lines:
        if "CrashedByAdbException" in line:
            print("AM_CRASH_DETECTED")
            return 1

    # ── Block splitting ───────────────────────────────────────────────────
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

    # ── PID reuse detection ───────────────────────────────────────────────
    # A real crash produces exactly ONE FATAL EXCEPTION block per PID.
    # PID-reuse attacks produce 2+ blocks (original crash + forge).
    if len(blocks) != 1:
        print(f"PID_REUSE_DETECTED:{len(blocks)}_blocks")
        return 1

    # ── Signature check ───────────────────────────────────────────────────
    block = blocks[0]
    has_process = (f"Process: {app_package}, PID: {crash_pid}" in block) or (
        f"Process: {app_package}" in block
    )
    has_exception = (
        re.search(r"IllegalArgumentException: bad base-64", block) is not None
    )
    # Use substring match (not \b word boundary) because the 'printable' logcat
    # modifier escapes the leading tab in stack frames (\t -> \\t), which makes
    # \bat fail to match.  The substring 'at <class>.<method>' is specific enough.
    has_method = "at io.heckel.ntfy.util.UtilKt.decodeMessage" in block
    has_base64 = "at android.util.Base64.decode" in block

    if has_process and has_exception and has_method and has_base64:
        print("MATCH")
        return 0

    print("NO_MATCH")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
