#!/usr/bin/env python3
"""Subset comparison for optional remote-attacker score fixtures.

Treats the expected JSON as a required subset of the actual JSON: every
key/value present in expected must match exactly, while extra actual
diagnostics (e.g. dynamic `details` blocks with timestamps, row counts,
evidence excerpts) are ignored.

Usage:
    compare_score_subset.py <expected.json> <actual.json>

Exit codes:
    0  expected is a subset of actual
    1  one or more mismatches (printed to stderr)
    2  failed to load either JSON file
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def walk(exp: object, act: object, path: str, mismatches: list[str]) -> None:
    if isinstance(exp, dict):
        if not isinstance(act, dict):
            mismatches.append(f"{path}: expected object, got {type(act).__name__}")
            return
        for key, exp_value in exp.items():
            next_path = f"{path}.{key}" if path else key
            if key not in act:
                mismatches.append(f"{next_path}: missing from actual")
                continue
            walk(exp_value, act[key], next_path, mismatches)
        return
    if exp != act:
        mismatches.append(f"{path}: expected {exp!r}, got {act!r}")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} <expected.json> <actual.json>", file=sys.stderr)
        return 2
    try:
        expected = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        actual = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"failed to load JSON: {exc}", file=sys.stderr)
        return 2

    mismatches: list[str] = []
    walk(expected, actual, "", mismatches)
    if mismatches:
        print("score subset mismatches:", file=sys.stderr)
        for item in mismatches:
            print(f"  - {item}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
