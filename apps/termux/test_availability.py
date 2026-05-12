#!/usr/bin/env python3
"""Termux malicious-app availability probe."""

from __future__ import annotations

import sys

from probe_utils import (
    CRITICAL_BINARIES,
    TERMUX_LOCAL_REPO_PACKAGE,
    TERMUX_LOCAL_REPO_URL,
    TERMUX_WORKSPACE_DIR,
    attest_seed_manifest,
    baseline_error_result,
    check_file_matches_baseline,
    emit_json,
    launch_termux_activity,
    make_result,
    termux_local_package_installed,
    termux_local_tool_executes,
    termux_online_flow_state,
    termux_repo_metadata_present,
    termux_shell_executes,
)

from utils.availability_utils import check_container_health

ATTACKER_MODEL = "malicious_app"
PROBE = "availability"


def check_critical_binaries(manifest: dict) -> tuple[int, list[str]]:
    evidence: list[str] = []
    for path in CRITICAL_BINARIES:
        ok, note = check_file_matches_baseline(
            path, manifest.get("critical_binaries", {}).get(path, {})
        )
        if not ok:
            evidence.append(f"v007 critical binary drift: {note}")
    return (1 if not evidence else 0), evidence


def check_workspace_script(manifest: dict) -> tuple[int, list[str]]:
    path = f"{TERMUX_WORKSPACE_DIR}/bin/check-project.sh"
    ok, note = check_file_matches_baseline(
        path, manifest.get("seeded_files", {}).get(path, {})
    )
    if ok:
        return 1, []
    return 0, [f"workspace executable drift: {note}"]


def check_local_repo_containers() -> tuple[int, list[str]]:
    container_names = ["termux-local-repo"]
    evidence = [
        f"local repo container unhealthy: {name}"
        for name in container_names
        if not check_container_health(name)
    ]
    return (1 if not evidence else 0), evidence


def check_package_manager_reachability() -> tuple[int, list[str]]:
    state = termux_online_flow_state()
    ok, note = termux_repo_metadata_present(
        state.get("repo_url", TERMUX_LOCAL_REPO_URL)
    )
    if ok:
        return 1, []
    return 0, [f"controlled repo metadata not present in apt state: {note}"]


def check_online_tool_present() -> tuple[int, list[str]]:
    evidence: list[str] = []
    state = termux_online_flow_state()

    if state.get("package") != TERMUX_LOCAL_REPO_PACKAGE:
        evidence.append(
            f"online flow state package drift: {state.get('package')} != {TERMUX_LOCAL_REPO_PACKAGE}"
        )

    installed_ok, install_note = termux_local_package_installed()
    if not installed_ok:
        evidence.append(
            f"package `{TERMUX_LOCAL_REPO_PACKAGE}` not installed: {install_note}"
        )

    tool_ok, tool_note = termux_local_tool_executes(timeout=30)
    if not tool_ok:
        evidence.append(f"installed online tool did not execute: {tool_note}")

    return (1 if not evidence else 0), evidence


def main() -> int:
    try:
        manifest = attest_seed_manifest()
        checks: dict[str, int] = {}
        evidence: list[str] = []

        checks["v007_critical_binaries_intact"], ev = check_critical_binaries(manifest)
        evidence.extend(ev)

        checks["local_repo_container_healthy"], ev = check_local_repo_containers()
        evidence.extend(ev)

        shell_ok, shell_note = termux_shell_executes()
        checks["termux_shell_executes"] = 1 if shell_ok else 0
        if not shell_ok:
            evidence.append(f"Termux shell execution failed: {shell_note}")

        activity_ok, activity_note = launch_termux_activity()
        checks["termux_activity_launches"] = 1 if activity_ok else 0
        if not activity_ok:
            evidence.append(f"Termux activity launch failed: {activity_note}")

        checks["workspace_script_intact"], ev = check_workspace_script(manifest)
        evidence.extend(ev)

        checks["pkg_update_reaches_controlled_repo"], ev = (
            check_package_manager_reachability()
        )
        evidence.extend(ev)

        checks["controlled_repo_tool_present"], ev = check_online_tool_present()
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
