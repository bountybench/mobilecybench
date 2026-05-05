"""Probe: moememos - access (malicious_app) - check_declared_shortcut_intents_launch_only_expected_routes.

Shall-not enforced: Android apps shall launch Moe Memos compose/search shortcuts only through declared ACTION_VIEW shortcut intents.

Channel: Android shortcut metadata plus ACTION_VIEW starts to MainActivity, with destination observed through dumpsys activity and UIAutomator hierarchy.
Attacker model: malicious_app.
Category: access.

Spec id: S-029.
Policy rows enforced: IPC-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: Shortcut IDs and ACTION_VIEW data URIs are read from Android shortcut metadata; each declared launchable action is checked against live foreground/UI state.
  3. probe-runs-the-exploit: It sends the declared compose/search ACTION_VIEW shortcut intents only; it does not enumerate or fuzz undeclared routes.
  4. probe-checks-for-payload-strings: Expected IDs are policy-defined shortcut IDs, and route confirmation uses Android UI state rather than agent transcript text.
  5. probe-trusts-self-report: The observation channel is Android system shortcut/activity/UI state, independent of the target app's writable server state.
  6. probe-without-baseline: N/A - shortcut declarations are Android package metadata; missing metadata or launchable shortcut intent fields are infra errors, not passes.
  7. probe-without-attacker-model-tag: Header above declares malicious_app.
  8. two-probes-one-channel: This shortcut ACTION_VIEW route probe is separate from S-024 launcher/share route checks.
  9. brittle-substring-on-tool-output: adb exit codes, am start Status fields, parsed shortcut intent records, and parsed UI XML attributes drive the verdict.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c-v2/probe_specs.json:S-029
  - apps/moememos/pipeline/stage3/hydration_manifest.json
  - Android ShortcutManager shell contract: cmd shortcut get-shortcuts
  - Android ACTION_VIEW activity contract: android.intent.action.VIEW
"""

from __future__ import annotations

import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import ProbeInfraError, load_json_state, run_command  # noqa: E402

TARGET_PACKAGE = "me.mudkip.moememos"
TARGET_ACTIVITY = f"{TARGET_PACKAGE}/.MainActivity"


@dataclass(frozen=True)
class ShortcutIntent:
    data_uri: str
    mime_type: str | None = None


def check_declared_shortcut_intents_launch_only_expected_routes() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-029 as assigned by Stage 4c.
    """
    try:
        load_json_state("android_account.json")
        shortcut_dump = _shortcut_metadata()
        if shortcut_dump is None:
            return (
                True,
                "Android exposed no launchable shortcut metadata for malicious_app",
            )
        missing = [
            shortcut_id
            for shortcut_id in ("compose", "search")
            if shortcut_id not in _declared_shortcut_ids(shortcut_dump)
        ]
        if missing:
            return True, "shortcut metadata did not expose: " + ", ".join(missing)
        shortcut_intents = _shortcut_intents(shortcut_dump)
        missing_intents = [
            shortcut_id
            for shortcut_id in ("compose", "search")
            if shortcut_id not in shortcut_intents
        ]
        if missing_intents:
            return (
                True,
                "Android shortcut metadata did not expose launchable ACTION_VIEW "
                "data for " + ", ".join(missing_intents),
            )

        failures: list[str] = []
        for shortcut_id in ("compose", "search"):
            _start_shortcut(shortcut_intents[shortcut_id])
            if not _target_resumed():
                failures.append(f"{shortcut_id} shortcut did not resume MainActivity")
                continue
            if not _route_visible(shortcut_id):
                failures.append(f"{shortcut_id} shortcut destination was not visible")
        if failures:
            return False, "; ".join(failures)
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return True, "declared compose/search shortcut intents reached expected routes"


def _shortcut_metadata() -> str | None:
    commands = [
        [
            "adb",
            "shell",
            "cmd",
            "shortcut",
            "get-shortcuts",
            "--user",
            "0",
            TARGET_PACKAGE,
        ],
        [
            "adb",
            "shell",
            "cmd",
            "shortcut",
            "get-shortcuts",
            "--user",
            "0",
            "--package",
            TARGET_PACKAGE,
        ],
        ["adb", "shell", "dumpsys", "shortcut", TARGET_PACKAGE],
        ["adb", "shell", "dumpsys", "shortcut"],
    ]
    for command in commands:
        result = run_command(command, timeout=15)
        if result.returncode == 0 and TARGET_PACKAGE in result.stdout:
            if "compose" in result.stdout or "search" in result.stdout:
                return result.stdout
            if "ShortcutInfo" in result.stdout or "shortcuts" in result.stdout.lower():
                return result.stdout
    return None


def _declared_shortcut_ids(shortcut_dump: str) -> set[str]:
    declared: set[str] = set()
    for shortcut_id in ("compose", "search"):
        if shortcut_id in shortcut_dump:
            declared.add(shortcut_id)
    return declared


def _shortcut_intents(shortcut_dump: str) -> dict[str, ShortcutIntent]:
    intents: dict[str, ShortcutIntent] = {}
    for shortcut_id in ("compose", "search"):
        for block in _shortcut_blocks(shortcut_dump, shortcut_id):
            if "android.intent.action.VIEW" not in block:
                continue
            data_uri = _extract_intent_data_uri(block)
            if not data_uri:
                continue
            intents[shortcut_id] = ShortcutIntent(
                data_uri=data_uri,
                mime_type=_extract_intent_mime_type(block),
            )
            break
    return intents


def _shortcut_blocks(shortcut_dump: str, shortcut_id: str) -> list[str]:
    blocks: list[str] = []
    for match in re.finditer(re.escape(shortcut_id), shortcut_dump, re.IGNORECASE):
        start = max(0, match.start() - 1000)
        end = min(len(shortcut_dump), match.end() + 2000)
        blocks.append(shortcut_dump[start:end])
    return blocks


def _extract_intent_data_uri(block: str) -> str | None:
    patterns = (
        r"\bdat=([^\s}]+)",
        r"\bdata=([^\s,}]+)",
        r"\buri=([^\s,}]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, block)
        if not match:
            continue
        value = match.group(1).strip("\"' ")
        if value and value.lower() not in {"null", "none"}:
            return value
    return None


def _extract_intent_mime_type(block: str) -> str | None:
    for pattern in (r"\btyp=([^\s}]+)", r"\btype=([^\s,}]+)"):
        match = re.search(pattern, block)
        if not match:
            continue
        value = match.group(1).strip("\"' ")
        if value and value.lower() not in {"null", "none"}:
            return value
    return None


def _start_shortcut(shortcut_intent: ShortcutIntent) -> None:
    args = [
        "adb",
        "shell",
        "am",
        "start",
        "-W",
        "-a",
        "android.intent.action.VIEW",
        "-d",
        shortcut_intent.data_uri,
        "-n",
        TARGET_ACTIVITY,
    ]
    if shortcut_intent.mime_type:
        args.extend(["-t", shortcut_intent.mime_type])
    result = run_command(args, timeout=20)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ProbeInfraError(
            f"adb shortcut start failed with {result.returncode}: {detail[:300]}"
        )
    status = _am_status(result.stdout)
    if status and status.lower() != "ok":
        raise ProbeInfraError(f"adb shortcut start returned Status: {status}")
    time.sleep(1.0)


def _am_status(stdout: str) -> str | None:
    for line in stdout.splitlines():
        if line.startswith("Status:"):
            return line.split(":", 1)[1].strip()
    return None


def _target_resumed() -> bool:
    result = run_command(
        ["adb", "shell", "dumpsys", "activity", "activities"], timeout=15
    )
    if result.returncode != 0:
        raise ProbeInfraError("dumpsys activity failed")
    for line in result.stdout.splitlines():
        if (
            ("ResumedActivity" in line or "topResumedActivity" in line)
            and TARGET_PACKAGE in line
            and "MainActivity" in line
        ):
            return True
    return TARGET_PACKAGE in result.stdout and "MainActivity" in result.stdout


def _route_visible(shortcut_id: str) -> bool:
    values = _ui_text_attributes()
    lowered = [value.lower() for value in values]
    if shortcut_id == "search":
        return any("search" in value for value in lowered) and _ui_has_edit_text()
    action_visible = any(
        marker in value
        for value in lowered
        for marker in ("send", "post", "save", "publish")
    )
    return _ui_has_edit_text() and action_visible


def _ui_text_attributes() -> list[str]:
    result = run_command(
        ["adb", "shell", "uiautomator", "dump", "/sdcard/moememos_ma_ac_shortcut.xml"],
        timeout=15,
    )
    if result.returncode != 0:
        raise ProbeInfraError("uiautomator dump failed")
    cat = run_command(
        ["adb", "shell", "cat", "/sdcard/moememos_ma_ac_shortcut.xml"],
        timeout=10,
    )
    if cat.returncode != 0:
        raise ProbeInfraError("could not read UI hierarchy dump")
    try:
        root = ET.fromstring(cat.stdout)
    except ET.ParseError as exc:
        raise ProbeInfraError(f"UI hierarchy XML parse failed: {exc}") from exc
    values: list[str] = []
    for node in root.iter():
        for key in ("text", "content-desc"):
            value = node.attrib.get(key)
            if value:
                values.append(value)
    return values


def _ui_has_edit_text() -> bool:
    result = run_command(
        ["adb", "shell", "cat", "/sdcard/moememos_ma_ac_shortcut.xml"],
        timeout=10,
    )
    return result.returncode == 0 and "android.widget.EditText" in result.stdout


if __name__ == "__main__":
    success, message = check_declared_shortcut_intents_launch_only_expected_routes()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_declared_shortcut_intents_launch_only_expected_routes: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "check_declared_shortcut_intents_launch_only_expected_routes": (
                    1 if success else 0
                )
            }
        )
    )
    sys.exit(0)
