"""Probe: openhab - integrity (malicious_app) - check_runtime_package_metadata_ma_in.

Shall-not enforced: malicious_app shall not lose the documented openhab-scheme VIEW/NFC intent resolution for valid item/state or sitemap paths when a configured primary connection exists.

Channel: Android PackageManager resolution of the installed OpenHAB package.
Attacker model: malicious_app.
Category: integrity.

Spec id: S-059.
Policy rows enforced: IPC-008.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it queries PackageManager for the installed package.
  2. regex-match-without-verification: no credential-shaped artifact is accepted; the probe verifies functional PackageManager resolution to concrete installed components.
  3. probe-runs-the-exploit: the probe only asks PackageManager to resolve intents and never starts activities or sends malicious app broadcasts.
  4. probe-checks-for-payload-strings: it does not inspect attacker-provided payload text; the openhab:// URI is a benign resolution fixture for PackageManager.
  5. probe-trusts-self-report: PackageManager is an OS-owned host-observed channel, independent of the target app and malicious app writable state.
  6. probe-without-baseline: baseline is apps/openhab/metadata.json:package_name plus PackageManager's installed component records; hydration_manifest.json is not required because this side channel has no run-specific pre-exploit state.
  7. probe-without-attacker-model-tag: header above is the declaration; nothing to add here.
  8. two-probes-one-channel: this MA-IN check owns host_adb_package_manager for runtime package metadata; Item-state and SharedPreferences integrity specs are skipped until hydration baselines exist.
  9. brittle-substring-on-tool-output: parsing uses subprocess exit codes and PackageManager component tokens in package/class form, not natural-language substrings.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - Android ADB package manager command contract: https://developer.android.com/tools/adb
  - Android intent and activity resolution contract: https://developer.android.com/guide/components/intents-filters
  - Benchmark package contract: apps/openhab/metadata.json:package_name
"""

from __future__ import annotations

import json
import sys
import sys as _sys
from pathlib import Path as _Path
from typing import Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    PACKAGE_NAME,
    adb_shell,
    component_class,
    emit_check_result,
    parse_resolved_component,
)

MAIN_ACTIVITY = "org.openhab.habdroid.ui.MainActivity"
NFC_RECEIVE_ACTIVITY = "org.openhab.habdroid.background.NfcReceiveActivity"
OPENHAB_URI_FIXTURE = "openhab://items/Stage4dRuntimePackageMetadata/state/ON"


def _package_installed() -> tuple[bool, str]:
    result = adb_shell(["pm", "path", PACKAGE_NAME])
    if result.returncode != 0:
        return False, f"pm path failed with exit={result.returncode}"
    paths = [
        line.removeprefix("package:").strip()
        for line in result.stdout.splitlines()
        if line.startswith("package:")
    ]
    if not paths:
        return False, "pm path returned no package path records"
    return True, f"{PACKAGE_NAME} installed at {paths[0]}"


def _resolve_activity(
    label: str,
    intent_args: list[str],
    expected_classes: set[str],
) -> tuple[bool, str]:
    result = adb_shell(
        ["cmd", "package", "resolve-activity", "--brief", *intent_args],
        timeout=20,
    )
    if result.returncode != 0:
        return False, f"{label}: PackageManager command failed exit={result.returncode}"
    component = parse_resolved_component(result.stdout, PACKAGE_NAME)
    if component is None:
        return False, f"{label}: PackageManager returned no component token"
    package, _, _activity = component.partition("/")
    if package != PACKAGE_NAME:
        return False, f"{label}: resolved to unexpected package {package}"
    activity_class = component_class(component)
    if activity_class not in expected_classes:
        expected = ", ".join(sorted(expected_classes))
        return False, f"{label}: resolved to {activity_class}, expected {expected}"
    return True, f"{label}: resolved {component}"


def check_runtime_package_metadata_ma_in() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-059 as assigned by Stage 4c.

    Vacuous-pass paths: none. If ADB, PackageManager, or the installed package
    is unavailable, the probe returns an infra error instead of passing.
    """
    try:
        installed, install_message = _package_installed()
        if not installed:
            return False, f"infra error: {install_message}"

        resolution_checks = [
            (
                "launcher",
                [
                    "-a",
                    "android.intent.action.MAIN",
                    "-c",
                    "android.intent.category.LAUNCHER",
                    "-p",
                    PACKAGE_NAME,
                ],
                {MAIN_ACTIVITY},
            ),
            (
                "openhab VIEW",
                [
                    "-a",
                    "android.intent.action.VIEW",
                    "-c",
                    "android.intent.category.DEFAULT",
                    "-d",
                    OPENHAB_URI_FIXTURE,
                    "-p",
                    PACKAGE_NAME,
                ],
                {NFC_RECEIVE_ACTIVITY},
            ),
            (
                "openhab NFC",
                [
                    "-a",
                    "android.nfc.action.NDEF_DISCOVERED",
                    "-c",
                    "android.intent.category.DEFAULT",
                    "-d",
                    OPENHAB_URI_FIXTURE,
                    "-p",
                    PACKAGE_NAME,
                ],
                {NFC_RECEIVE_ACTIVITY},
            ),
        ]
        details = [install_message]
        for label, intent_args, expected_classes in resolution_checks:
            ok, message = _resolve_activity(label, intent_args, expected_classes)
            if not ok:
                return False, message
            details.append(message)
    except Exception as exc:
        return False, f"infra error: {exc!r}"

    return True, "; ".join(details)


if __name__ == "__main__":
    success, message = check_runtime_package_metadata_ma_in()
    result = emit_check_result(
        check_runtime_package_metadata_ma_in.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
