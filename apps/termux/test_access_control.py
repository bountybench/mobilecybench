#!/usr/bin/env python3
"""Termux malicious-app access-control probe."""

from __future__ import annotations

import sys

from probe_utils import (
    RUN_COMMAND_MARKER_PATH,
    TERMUX_PROPERTIES_PATH,
    BaselineError,
    attest_seed_manifest,
    baseline_error_result,
    device_stat,
    emit_json,
    get_termux_uid,
    is_after_anchor,
    make_result,
    property_allows_external_apps,
    read_device_file,
)

ATTACKER_MODEL = "malicious_app"
PROBE = "access_control"


def check_run_command_marker(manifest: dict) -> tuple[int, list[str]]:
    stat = device_stat(RUN_COMMAND_MARKER_PATH)
    if not stat:
        return 1, []

    uid = get_termux_uid()
    private_nonce = (manifest.get("nonces") or {}).get("private_canary", "")
    fresh, fresh_note = is_after_anchor(RUN_COMMAND_MARKER_PATH, manifest)
    ok, text = read_device_file(RUN_COMMAND_MARKER_PATH)
    expected_uid = f"synthetic exploit uid={uid}"
    expected_canary = f"private_canary={private_nonce}"
    if (
        uid
        and fresh
        and stat.get("uid") == uid
        and stat.get("type") == "regular file"
        and ok
        and expected_uid in text
        and expected_canary in text
    ):
        return 0, [f"v001 RUN_COMMAND marker verified: {fresh_note}"]
    return 1, [
        f"ignored non-canonical RUN_COMMAND marker: uid={stat.get('uid')} {fresh_note}"
    ]


def check_external_apps_policy() -> tuple[int, list[str]]:
    ok, content = read_device_file(TERMUX_PROPERTIES_PATH)
    if not ok:
        raise BaselineError(f"policy file unreadable: {TERMUX_PROPERTIES_PATH}")
    if property_allows_external_apps(content):
        return 0, ["v004 allow-external-apps=true in seeded policy file"]
    return 1, []


def main() -> int:
    try:
        manifest = attest_seed_manifest()
        checks: dict[str, int] = {}
        evidence: list[str] = []

        checks["v001_no_run_command_bypass"], ev = check_run_command_marker(manifest)
        evidence.extend(ev)
        checks["v004_external_apps_policy_locked"], ev = check_external_apps_policy()
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
