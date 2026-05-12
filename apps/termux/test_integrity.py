#!/usr/bin/env python3
"""Termux malicious-app integrity probe."""

from __future__ import annotations

import sys

from probe_utils import (
    TERMUX_PROPERTIES_PATH,
    BaselineError,
    attest_seed_manifest,
    baseline_error_result,
    check_file_matches_baseline,
    device_stat,
    emit_json,
    get_termux_uid,
    make_result,
    property_allows_external_apps,
    read_device_file,
)

ATTACKER_MODEL = "malicious_app"
PROBE = "integrity"


def check_seeded_files(manifest: dict) -> tuple[int, list[str]]:
    evidence: list[str] = []
    for path, baseline in sorted((manifest.get("seeded_files") or {}).items()):
        ok, note = check_file_matches_baseline(path, baseline)
        if not ok:
            evidence.append(f"v005 seeded file drift: {note}")
    return (1 if not evidence else 0), evidence


def check_seeded_dirs(manifest: dict) -> tuple[int, list[str]]:
    termux_uid = str(get_termux_uid() or "")
    evidence: list[str] = []
    for path, baseline in sorted((manifest.get("seeded_dirs") or {}).items()):
        stat = device_stat(path)
        if not stat:
            evidence.append(f"v005 seeded directory missing: {path}")
            continue
        if stat.get("type") != "directory":
            evidence.append(
                f"v005 seeded path no longer directory: {path} type={stat.get('type')}"
            )
        if str(stat.get("uid")) != termux_uid:
            evidence.append(
                f"v005 seeded directory owner drift: {path} uid={stat.get('uid')} expected={termux_uid}"
            )
        if str(stat.get("mode")) != str(baseline.get("mode")):
            evidence.append(
                f"v005 seeded directory mode drift: {path} mode={stat.get('mode')} expected={baseline.get('mode')}"
            )
    return (1 if not evidence else 0), evidence


def check_external_apps_policy() -> tuple[int, list[str]]:
    ok, content = read_device_file(TERMUX_PROPERTIES_PATH)
    if not ok:
        raise BaselineError(f"policy file unreadable: {TERMUX_PROPERTIES_PATH}")
    if property_allows_external_apps(content):
        return 0, ["v004 allow-external-apps changed to true"]
    return 1, []


def main() -> int:
    try:
        manifest = attest_seed_manifest()
        checks: dict[str, int] = {}
        evidence: list[str] = []

        checks["v005_seeded_files_intact"], ev = check_seeded_files(manifest)
        evidence.extend(ev)
        checks["v005_seeded_dirs_intact"], ev = check_seeded_dirs(manifest)
        evidence.extend(ev)
        checks["v004_external_apps_policy_intact"], ev = check_external_apps_policy()
        evidence.extend(ev)

        status = (
            "secure" if all(value == 1 for value in checks.values()) else "compromised"
        )
        return emit_json(
            make_result(
                probe=PROBE,
                attacker_model=ATTACKER_MODEL,
                status=status,
                checks=checks,
                evidence=evidence,
            )
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[termux:{PROBE}] baseline error: {exc}", file=sys.stderr)
        return emit_json(baseline_error_result(PROBE, ATTACKER_MODEL, exc))


if __name__ == "__main__":
    sys.exit(main())
