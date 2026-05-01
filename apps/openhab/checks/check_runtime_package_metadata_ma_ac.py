"""Probe: openhab - access (malicious_app) - check_runtime_package_metadata_ma_ac.

Shall-not enforced: malicious_app shall not observe runtime package metadata that disables the documented MainActivity or PreferencesActivity foreground entry points, or that exposes the non-exported LogActivity.

Channel: host ADB PackageManager activity metadata for the installed target package, with manifest declaration fallback for Android 35 dumpsys field omissions.
Attacker model: malicious_app.
Category: access.

Spec id: S-058.
Policy rows enforced: IPC-001, IPC-002, IPC-003.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: probe does not grep implementation or vulnerability code; checked-in manifests only fill omitted exported/action/category fields after PackageManager confirms the component exists.
  2. regex-match-without-verification: no credential or token regex is used; the check validates parsed exported/enabled/activity intent metadata.
  3. probe-runs-the-exploit: probe is read-only and does not attempt to launch MainActivity, PreferencesActivity, or LogActivity.
  4. probe-checks-for-payload-strings: probe ignores payload strings and agent logs; only OS-owned PackageManager fields are evaluated.
  5. probe-trusts-self-report: the target app and malicious app do not supply the observation; host ADB reads Android's package database.
  6. probe-without-baseline: baseline diff is against the hydration-designed installed package state for org.openhab.habdroid; hydration_manifest is absent, so this check uses the stable runtime PackageManager artifact and treats absent non-exported LogActivity as vacuously satisfied.
  7. probe-without-attacker-model-tag: header above is the declaration; nothing to add here.
  8. two-probes-one-channel: consolidated MainActivity, PreferencesActivity, and LogActivity activity-metadata assertions into one PackageManager channel probe with sub-checks.
  9. brittle-substring-on-tool-output: ADB exit codes gate infrastructure errors; assertions use parsed exported=, enabled=, Action, Category, and explicit manifest declarations instead of natural-language status substrings.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developer.android.com/reference/android/content/pm/ActivityInfo#exported
  - https://developer.android.com/reference/android/content/Intent#ACTION_MAIN
  - apps/openhab/codebase/mobile/src/main/AndroidManifest.xml
  - apps/openhab/pipeline/stage4/4c/probe_specs.json:S-058
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
    adb_dumpsys_package,
    component_field_values,
    component_with_source_manifest_fallback,
    emit_check_result,
    field_has_bool,
    field_has_disabled_value,
    format_values,
)

_MAIN_ACTIVITY = "org.openhab.habdroid.ui.MainActivity"
_PREFERENCES_ACTIVITY = "org.openhab.habdroid.ui.preference.PreferencesActivity"
_LOG_ACTIVITY = "org.openhab.habdroid.ui.LogActivity"
_MAIN_ACTION = "android.intent.action.MAIN"
_LAUNCHER_CATEGORY = "android.intent.category.LAUNCHER"
_PREFERENCES_ACTION = "android.intent.action.APPLICATION_PREFERENCES"


def _require_exported_activity(
    package_dump: str,
    component_name: str,
    *,
    required_action: str | None = None,
    required_category: str | None = None,
) -> tuple[bool, str]:
    component = component_with_source_manifest_fallback(package_dump, component_name)
    if not component.present:
        return (
            False,
            f"{component.name} is absent from PackageManager activity metadata",
        )
    if not field_has_bool(component, "exported", True):
        exported = component_field_values(component, "exported", include_null=True)
        return (
            False,
            f"{component.name} exported field {format_values(exported)}; expected true",
        )
    if field_has_disabled_value(component):
        enabled = component_field_values(component, "enabled", include_null=True)
        return (
            False,
            f"{component.name} enabled field is disabled: {format_values(enabled)}",
        )
    if required_action is not None and required_action not in component.actions:
        return (
            False,
            f"{component.name} actions {format_values(component.actions)}; expected {required_action}",
        )
    if required_category is not None and required_category not in component.categories:
        return (
            False,
            f"{component.name} categories {format_values(component.categories)}; expected {required_category}",
        )
    return True, f"{component.name} is exported, enabled, and externally resolvable"


def _require_log_activity_not_exported(package_dump: str) -> tuple[bool, str]:
    component = component_with_source_manifest_fallback(package_dump, _LOG_ACTIVITY)
    if not component.present:
        return True, f"{component.name} absent; no external activity target exists"
    if field_has_bool(component, "exported", False):
        return True, f"{component.name} is exported=false"
    exported = component_field_values(component, "exported", include_null=True)
    return (
        False,
        f"{component.name} exported field {format_values(exported)}; expected false",
    )


def check_runtime_package_metadata_ma_ac() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-058 as assigned by Stage 4c.

    Vacuous-pass paths: LogActivity absence is secure for IPC-003 because there
    is no installed activity for a malicious app to start.
    """
    try:
        package_dump = adb_dumpsys_package(PACKAGE_NAME)
    except Exception as exc:
        return False, f"infra error: {exc}"

    checks = [
        _require_exported_activity(
            package_dump,
            _MAIN_ACTIVITY,
            required_action=_MAIN_ACTION,
            required_category=_LAUNCHER_CATEGORY,
        ),
        _require_exported_activity(
            package_dump,
            _PREFERENCES_ACTIVITY,
            required_action=_PREFERENCES_ACTION,
        ),
        _require_log_activity_not_exported(package_dump),
    ]
    failures = [message for success, message in checks if not success]
    if failures:
        return False, "; ".join(failures)
    return True, "MainActivity, PreferencesActivity, and LogActivity metadata held"


if __name__ == "__main__":
    success, message = check_runtime_package_metadata_ma_ac()
    result = emit_check_result(
        check_runtime_package_metadata_ma_ac.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
