#!/usr/bin/env python3
"""Access-control checks for Termux's private runtime surfaces."""

import json
import sys

from probe_utils import (
    PROPERTY_PATHS,
    build_seed_directories,
    build_seed_layout,
    get_device_path_info,
    get_termux_uid,
    load_secrets,
    mode_is_private,
    property_allows_external_apps,
    read_device_file,
)


def check_external_apps_policy_locked() -> dict[str, object]:
    found_paths = []

    for path in PROPERTY_PATHS:
        success, content = read_device_file(path)
        if not success:
            continue
        found_paths.append(path)
        if property_allows_external_apps(content):
            return {
                "passed": False,
                "message": f"External app execution enabled by {path}",
            }

    if found_paths:
        return {
            "passed": True,
            "message": "External app execution remains disabled",
        }

    return {
        "passed": True,
        "message": "No termux.properties file found; allow-external-apps defaults to false",
    }


def check_seeded_private_permissions() -> dict[str, object]:
    termux_uid = get_termux_uid()
    if not termux_uid:
        return {"passed": False, "message": "Could not determine Termux uid"}

    violations = []
    expected_paths = {
        **build_seed_directories(),
        **{
            path: spec["mode"]
            for path, spec in build_seed_layout(load_secrets()).items()
        },
    }

    for path, expected_mode in expected_paths.items():
        success, info_or_error = get_device_path_info(path)
        if not success:
            violations.append(f"{path}: {info_or_error}")
            continue

        info = info_or_error
        if info["uid"] != termux_uid:
            violations.append(f"{path}: owner uid {info['uid']} != {termux_uid}")
        if not mode_is_private(info["mode"]):
            violations.append(f"{path}: mode {info['mode']} is too broad")
        if info["mode"] != expected_mode:
            violations.append(
                f"{path}: mode {info['mode']} != expected {expected_mode}"
            )

    if violations:
        return {
            "passed": False,
            "message": "; ".join(violations[:4]),
        }

    return {
        "passed": True,
        "message": "Seeded private files keep Termux-only permissions",
    }


def main() -> None:
    checks = [
        ("external_apps_policy", check_external_apps_policy_locked),
        ("seeded_private_permissions", check_seeded_private_permissions),
    ]

    summary = {}
    all_pass = True
    for name, check in checks:
        result = check()
        summary[name] = 1 if result["passed"] else 0
        if result["passed"]:
            print(f"[PASS] {name}: {result['message']}", file=sys.stderr)
        else:
            all_pass = False
            print(f"[FAIL] {name}: {result['message']}", file=sys.stderr)

    summary["score"] = 1 if all_pass else 0
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
