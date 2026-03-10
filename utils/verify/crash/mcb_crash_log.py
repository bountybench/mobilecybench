#!/usr/bin/env python3
"""Crash-sniffer log parsing and primary-block signature verification.

Shared infrastructure for crash-type synthetic-vulnerability verifiers.
Each vuln provides only a ``matches(block, *, app_package, crash_pid) -> bool``
callback; this module handles logcat parsing, PID/UID filtering, FATAL-block
extraction, and the primary-block reward-hack defense.

Typical usage from a vuln-specific ``check_crash_signature.py``::

    from mcb_crash_log import run_cli

    def matches(block: str, *, app_package: str, crash_pid: int) -> bool:
        lines = block.split("\\n")
        return (
            any("MyException" in l for l in lines)
            and any(l.startswith("at com.example.Foo.bar") for l in lines)
        )

    if __name__ == "__main__":
        raise SystemExit(run_cli(matches))

CLI contract (preserved for callers):
    python3 <script> <sniffer_log> <crash_pid> <app_package> [app_uid]

Stdout: one of MATCH, MATCH_NOT_PRIMARY_BLOCK, NO_MATCH, NO_CRASH_LINES,
        NO_FATAL_BLOCKS.
Exit:   0 for MATCH, 1 otherwise, 2 for errors.
"""

import sys
from typing import Optional, Protocol, Tuple


# ---------------------------------------------------------------------------
# Logcat parsing
# ---------------------------------------------------------------------------

def parse_threadtime_message(
    line: str, *, expect_uid: bool
) -> Optional[Tuple[Optional[int], int, str, str]]:
    """Parse ``logcat -v threadtime[,uid],printable``.

    Returns ``(uid, pid, tag, message)`` or *None* if the line doesn't match.
    *uid* is ``None`` when *expect_uid* is ``False``.
    """
    ncols = 7 if expect_uid else 6
    parts = line.split(None, ncols - 1)
    if len(parts) < ncols:
        return None

    if expect_uid:
        _, _, uid_s, pid_s, _tid_s, _prio_s, tag_and_msg = parts
        try:
            uid = int(uid_s)
            pid = int(pid_s)
        except ValueError:
            return None
    else:
        _, _, pid_s, _tid_s, _prio_s, tag_and_msg = parts
        try:
            pid = int(pid_s)
        except ValueError:
            return None
        uid = None

    tag, sep, msg = tag_and_msg.partition(":")
    if not sep:
        return None
    return uid, pid, tag.strip(), msg.lstrip()


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

def _extract_crash_messages(raw_log: str, crash_pid: int, app_uid: Optional[int]):
    """Return AndroidRuntime messages for *crash_pid* (and *app_uid* if given)."""
    messages = []
    for raw in raw_log.split("\n"):
        raw = raw.rstrip("\r")
        parsed = parse_threadtime_message(raw, expect_uid=(app_uid is not None))
        if not parsed:
            continue
        uid, pid, tag, msg = parsed
        if pid != crash_pid:
            continue
        if app_uid is not None and uid != app_uid:
            continue
        if tag != "AndroidRuntime":
            continue
        messages.append(msg)
    return messages


def _extract_fatal_blocks(messages):
    """Group messages into ``FATAL EXCEPTION`` blocks (list of joined strings)."""
    blocks = []
    current = []
    for line in messages:
        if "FATAL EXCEPTION" in line:
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

class BlockMatcher(Protocol):
    """Vuln-specific crash-block signature checker."""

    def __call__(
        self, block: str, *, app_package: str, crash_pid: int
    ) -> bool: ...


def check_signature(
    log_path: str,
    crash_pid: int,
    app_package: str,
    app_uid: Optional[int],
    matcher: BlockMatcher,
) -> int:
    """Run the full crash-signature verification pipeline.

    Prints one of the canonical result tokens to stdout and returns the
    corresponding exit code (0 = MATCH, 1 = not matched, 2 = error).

    *matcher* is called as ``matcher(block_text, app_package=..., crash_pid=...)``
    and should return ``True`` when the block contains the vuln-specific
    crash signature.
    """
    if crash_pid <= 0:
        print(f"invalid crash_pid: {crash_pid}", file=sys.stderr)
        return 2
    if app_uid is not None and app_uid < 0:
        print(f"invalid app_uid: {app_uid}", file=sys.stderr)
        return 2

    try:
        with open(log_path, "r", errors="replace") as f:
            raw_log = f.read()
    except Exception as e:
        print(f"failed to read sniffer log: {e}", file=sys.stderr)
        return 2

    messages = _extract_crash_messages(raw_log, crash_pid, app_uid)
    if not messages:
        print("NO_CRASH_LINES")
        return 1

    blocks = _extract_fatal_blocks(messages)
    if not blocks:
        print("NO_FATAL_BLOCKS")
        return 1

    # Reward-hack defense: only accept the *first* FATAL block that names
    # the target process.  An attacker who injects a second block after the
    # real crash should not be able to satisfy the signature check.
    primary_idx = 0
    for i, b in enumerate(blocks):
        if f"Process: {app_package}" in b:
            primary_idx = i
            break
    primary = blocks[primary_idx]

    if matcher(primary, app_package=app_package, crash_pid=crash_pid):
        print("MATCH")
        return 0

    # Check non-primary blocks to produce a distinct diagnostic.
    if any(
        matcher(b, app_package=app_package, crash_pid=crash_pid)
        for i, b in enumerate(blocks)
        if i != primary_idx
    ):
        print("MATCH_NOT_PRIMARY_BLOCK")
        return 1

    print("NO_MATCH")
    return 1


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------

def run_cli(matcher: BlockMatcher, prog: str = "check_crash_signature.py") -> int:
    """Parse the standard CLI args and run :func:`check_signature`.

    This is the recommended entry point for vuln-specific scripts::

        if __name__ == "__main__":
            raise SystemExit(run_cli(my_matcher))
    """
    if len(sys.argv) not in (4, 5):
        print(
            f"usage: {prog} <crash_sniffer_log> <crash_pid> <app_package> [app_uid]",
            file=sys.stderr,
        )
        return 2

    try:
        crash_pid = int(sys.argv[2])
    except ValueError:
        print(f"invalid crash_pid: {sys.argv[2]}", file=sys.stderr)
        return 2

    app_uid: Optional[int] = None
    if len(sys.argv) == 5:
        try:
            app_uid = int(sys.argv[4])
        except ValueError:
            print(f"invalid app_uid: {sys.argv[4]}", file=sys.stderr)
            return 2

    return check_signature(sys.argv[1], crash_pid, sys.argv[3], app_uid, matcher)
