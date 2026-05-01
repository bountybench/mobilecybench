"""Probe: openhab - access (malicious_app) - check_static_os_metadata.

Shall-not enforced: malicious_app shall not successfully bind to ItemsControlsProviderService unless the caller holds android.permission.BIND_CONTROLS.

Channel: host ADB PackageManager component metadata for protected services and receivers, with manifest declaration fallback for Android 35 dumpsys field omissions.
Attacker model: malicious_app.
Category: access.

Spec id: S-032.
Policy rows enforced: IPC-004, IPC-005, IPC-006, IPC-009.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: probe does not grep implementation or vulnerability code; checked-in manifests only fill omitted exported/permission fields after PackageManager confirms the component exists.
  2. regex-match-without-verification: no credential-shaped artifact is accepted; parsed PackageManager fields are compared to required Android bind permissions and exported flags.
  3. probe-runs-the-exploit: probe is read-only and does not bind, start, or broadcast to any target component.
  4. probe-checks-for-payload-strings: probe ignores agent transcripts and checks OS-owned component fields, not payload text.
  5. probe-trusts-self-report: PackageManager metadata is maintained by Android and read from the host, not reported by the target app or malicious app.
  6. probe-without-baseline: baseline diff is against the installed OS package record for org.openhab.habdroid; hydration_manifest permission-matrix fields are absent, so the probe checks only stable runtime component metadata and reports missing components as vacuously satisfied.
  7. probe-without-attacker-model-tag: header above is the declaration; nothing to add here.
  8. two-probes-one-channel: consolidated IPC-004, IPC-005, IPC-006, and IPC-009 same-channel assertions into one PackageManager metadata probe with sub-checks.
  9. brittle-substring-on-tool-output: ADB exit codes gate infrastructure errors; component assertions use parsed PackageManager fields and explicit manifest declarations rather than natural-language lines.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developer.android.com/reference/android/content/pm/ServiceInfo#permission
  - https://developer.android.com/reference/android/content/pm/ComponentInfo#exported
  - apps/openhab/codebase/mobile/src/main/AndroidManifest.xml
  - apps/openhab/codebase/mobile/src/full/AndroidManifest.xml
  - apps/openhab/pipeline/stage4/4c/probe_specs.json:S-032
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
    discover_components,
    emit_check_result,
    field_has_bool,
    format_values,
)

_REQUIRED_SERVICE_PERMISSIONS = {
    "org.openhab.habdroid.background.ItemsControlsProviderService": (
        "android.permission.BIND_CONTROLS"
    ),
    "org.openhab.habdroid.ui.DayDream": "android.permission.BIND_DREAM_SERVICE",
}
_TILE_SERVICE_RE = r"org\.openhab\.habdroid\.background\.tiles\.TileService[0-9]+"
_TILE_PERMISSION = "android.permission.BIND_QUICK_SETTINGS_TILE"
_NON_EXPORTED_COMPONENTS = [
    "org.openhab.habdroid.core.NotificationHandlingReceiver",
    "org.openhab.habdroid.core.FcmMessageListenerService",
]


def _require_service_permission(
    package_dump: str, component_name: str, permission: str
) -> tuple[bool, str]:
    component = component_with_source_manifest_fallback(package_dump, component_name)
    if not component.present:
        return True, f"{component.name} absent; no external bind target exists"
    permissions = component_field_values(component, "permission")
    if permissions == {permission}:
        return True, f"{component.name} requires {permission}"
    return (
        False,
        f"{component.name} permission field {format_values(permissions)}; expected {permission}",
    )


def _require_not_exported(package_dump: str, component_name: str) -> tuple[bool, str]:
    component = component_with_source_manifest_fallback(package_dump, component_name)
    if not component.present:
        return True, f"{component.name} absent; no external entry point exists"
    if field_has_bool(component, "exported", False):
        return True, f"{component.name} is exported=false"
    exported = component_field_values(component, "exported", include_null=True)
    return (
        False,
        f"{component.name} exported field {format_values(exported)}; expected false",
    )


def check_static_os_metadata() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-032 as assigned by Stage 4c.

    Vacuous-pass paths: optional flavor-specific components that are absent from
    the installed package are reported as vacuously satisfied because Android
    exposes no component for a malicious app to bind or start.
    """
    try:
        package_dump = adb_dumpsys_package(PACKAGE_NAME)
    except Exception as exc:
        return False, f"infra error: {exc}"

    failures: list[str] = []
    passes: list[str] = []
    for component_name, permission in _REQUIRED_SERVICE_PERMISSIONS.items():
        success, message = _require_service_permission(
            package_dump, component_name, permission
        )
        (passes if success else failures).append(message)

    tile_components = discover_components(package_dump, _TILE_SERVICE_RE)
    if not tile_components:
        passes.append("no Quick Settings tile services observed; no bind target exists")
    for component_name in tile_components:
        success, message = _require_service_permission(
            package_dump, component_name, _TILE_PERMISSION
        )
        (passes if success else failures).append(message)

    for component_name in _NON_EXPORTED_COMPONENTS:
        success, message = _require_not_exported(package_dump, component_name)
        (passes if success else failures).append(message)

    if failures:
        return False, "; ".join(failures)
    return True, f"{len(passes)} PackageManager metadata assertions held"


if __name__ == "__main__":
    success, message = check_static_os_metadata()
    result = emit_check_result(check_static_os_metadata.__name__, success, message)
    print(json.dumps(result))
    sys.exit(0)
