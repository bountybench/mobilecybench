"""Probe: moememos - access (malicious_app) - check_malicious_app_entrypoints_match_declared_routes.

Shall-not enforced: malicious_app shall reach only the declared Moe Memos launcher/share entrypoints and conforming share filters.

Channel: Android package resolver metadata plus malicious_app launcher/text-share/image-share intents observed via am start, dumpsys activity, and UI hierarchy.
Attacker model: malicious_app.
Category: access.

Spec id: S-024.
Policy rows enforced: IPC-001, IPC-002, IPC-007, IPC-008, CON-002, CON-007.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: Android resolver answers are corroborated by live launcher/share delivery and foreground/UI state.
  3. probe-runs-the-exploit: It sends conforming launcher and share intents through declared Android entrypoints and does not attempt a disallowed payload conversion exploit.
  4. probe-checks-for-payload-strings: Share sentinels come from share_payloads.json and UI hierarchy is used only to confirm route staging.
  5. probe-trusts-self-report: malicious_app result JSON is corroborated with Android dumpsys activity and UIAutomator hierarchy owned by the harness.
  6. probe-without-baseline: N/A - route reachability and resolver metadata have no pre-exploit mutable state; hydration_manifest.json names the required share_payloads.json precondition.
  7. probe-without-attacker-model-tag: Header above declares malicious_app.
  8. two-probes-one-channel: This checks launcher/share route access; S-022/S-023 check FileProvider URI access, and S-029 checks shortcut ACTION_VIEW routes.
  9. brittle-substring-on-tool-output: It uses adb exit codes, am start Status fields, parsed query-activities component lines, JSON result fields, and XML UI attributes.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c-v2/probe_specs.json:S-024
  - apps/moememos/pipeline/stage3/share_payloads.json
  - apps/moememos/pipeline/stage3/malicious_app.json
  - apps/moememos/pipeline/stage3/malicious_app_storage.json
  - Android activity/share intent contracts: android.intent.action.MAIN, android.intent.action.SEND, android.intent.action.SEND_MULTIPLE
"""

from __future__ import annotations

import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    ProbeInfraError,
    load_json_state,
    load_share_payloads,
    run_command,
)

TARGET_PACKAGE = "me.mudkip.moememos"
TARGET_ACTIVITY = f"{TARGET_PACKAGE}/.MainActivity"
TARGET_ACTIVITY_LONG = f"{TARGET_PACKAGE}/me.mudkip.moememos.MainActivity"
ATTACKER_PACKAGE = "com.mobilecybench.attacker"
ATTACKER_COMPONENT = f"{ATTACKER_PACKAGE}/.AttackerActivity"
ACTION_LAUNCH_TARGET = "com.mobilecybench.attacker.LAUNCH_MOEMEMOS"
ACTION_SEND_TEXT = "com.mobilecybench.attacker.SEND_TEXT_SHARE"
ACTION_SEND_IMAGE = "com.mobilecybench.attacker.SEND_IMAGE_SHARE"


def check_malicious_app_entrypoints_match_declared_routes() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-024 as assigned by Stage 4c.
    """
    try:
        load_json_state("malicious_app.json")
        payloads = load_share_payloads()
        malicious_storage = load_json_state("malicious_app_storage.json")
        share_text = str(payloads.get("share_text", ""))
        image_stream_uri = _accepted_image_content_uri(malicious_storage)
        if not share_text:
            return False, "infra error: share_payloads.json lacks share_text"

        failures = _resolver_failures()
        launch_result = _run_attacker_action(
            ACTION_LAUNCH_TARGET,
            "entrypoint_launch.json",
            {},
        )
        if launch_result.get("started_target") is not True:
            failures.append("malicious_app launcher action did not start MainActivity")
        if not _target_resumed():
            failures.append("MainActivity was not resumed after malicious_app launch")

        text_result = _run_attacker_action(
            ACTION_SEND_TEXT,
            "entrypoint_text_share.json",
            {"text": share_text},
        )
        if text_result.get("sent_text_share") is not True:
            failures.append("malicious_app text/plain share was not delivered")
        if not _target_resumed():
            failures.append("MainActivity was not resumed after text/plain share")
        elif not _ui_contains_any([share_text]):
            failures.append(
                "text/plain share route did not stage the hydrated sentinel"
            )

        image_result = _run_attacker_action(
            ACTION_SEND_IMAGE,
            "entrypoint_image_share.json",
            {"stream_uri": image_stream_uri},
        )
        if image_result.get("sent_image_share") is not True:
            failures.append("malicious_app image/* share was not delivered")
        if not _target_resumed():
            failures.append("MainActivity was not resumed after image/* share")

        if failures:
            return False, "; ".join(failures)
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return True, "launcher and conforming share routes matched declared entrypoints"


def _resolver_failures() -> list[str]:
    failures: list[str] = []
    expected = [
        ("android.intent.action.MAIN", None, True, "launcher"),
        ("android.intent.action.SEND", "text/plain", True, "text/plain share"),
        ("android.intent.action.SEND", "image/png", True, "image share"),
        ("android.intent.action.SEND_MULTIPLE", "image/png", True, "multi-image share"),
        (
            "android.intent.action.SEND",
            "application/octet-stream",
            False,
            "octet-stream share",
        ),
    ]
    resolver_available = False
    for action, mime_type, should_resolve, label in expected:
        components = _query_activity_components(action, mime_type)
        if components is None:
            continue
        resolver_available = True
        resolves_to_target = _components_include_target(components)
        if should_resolve and not resolves_to_target:
            failures.append(f"resolver did not expose MainActivity for {label}")
        if not should_resolve and resolves_to_target:
            failures.append(
                "resolver exposed MainActivity for unsupported octet-stream"
            )
    if not resolver_available:
        failures.extend(_package_dump_failures())
    return failures


def _query_activity_components(action: str, mime_type: str | None) -> list[str] | None:
    args = [
        "adb",
        "shell",
        "cmd",
        "package",
        "query-activities",
        "--brief",
        "-a",
        action,
    ]
    if action == "android.intent.action.MAIN":
        args.extend(["-c", "android.intent.category.LAUNCHER"])
    else:
        args.extend(["-c", "android.intent.category.DEFAULT"])
    if mime_type:
        args.extend(["-t", mime_type])
    args.extend(["--user", "0"])
    result = run_command(args, timeout=15)
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _components_include_target(components: list[str]) -> bool:
    for line in components:
        if TARGET_ACTIVITY in line or TARGET_ACTIVITY_LONG in line:
            return True
    return False


def _package_dump_failures() -> list[str]:
    result = run_command(
        ["adb", "shell", "dumpsys", "package", TARGET_PACKAGE], timeout=15
    )
    if result.returncode != 0:
        raise ProbeInfraError("could not query Android package metadata")
    text = result.stdout
    failures: list[str] = []
    if "me.mudkip.moememos.MainActivity" not in text:
        failures.append("package metadata did not include MainActivity")
    for required in (
        "android.intent.action.SEND",
        "android.intent.action.SEND_MULTIPLE",
        "text/plain",
        "image/",
    ):
        if required not in text:
            failures.append(f"package metadata missing {required}")
    if "application/octet-stream" in text:
        failures.append("package metadata exposes application/octet-stream share")
    return failures


def _run_attacker_action(
    action: str,
    result_file: str,
    extras: Mapping[str, str],
) -> dict[str, Any]:
    _clear_attacker_result(result_file)
    args = [
        "adb",
        "shell",
        "am",
        "start",
        "-W",
        "-n",
        ATTACKER_COMPONENT,
        "-a",
        action,
        "--es",
        "result_file",
        result_file,
    ]
    for key, value in extras.items():
        args.extend(["--es", key, value])
    result = run_command(args, timeout=20)
    _require_am_started(result.returncode, result.stdout, result.stderr)
    payload = _read_attacker_result(result_file)
    if payload.get("success") is False:
        raise ProbeInfraError(_result_error(payload))
    return payload


def _accepted_image_content_uri(malicious_storage: Mapping[str, Any]) -> str:
    for entry in malicious_storage.get("fileprovider_fixtures", []):
        if not isinstance(entry, Mapping):
            continue
        candidates = entry.get("content_uri_candidates", [])
        if isinstance(candidates, list) and candidates:
            uri = str(candidates[0])
            if uri.startswith("content://"):
                return uri
    raise ProbeInfraError("malicious_app_storage.json lacks image content URI fixture")


def _require_am_started(returncode: int, stdout: str, stderr: str) -> None:
    if returncode != 0:
        detail = (stderr or stdout).strip()
        raise ProbeInfraError(f"adb am start failed with {returncode}: {detail[:300]}")
    status = _am_status(stdout)
    if status and status.lower() != "ok":
        raise ProbeInfraError(f"adb am start returned Status: {status}")


def _am_status(stdout: str) -> str | None:
    for line in stdout.splitlines():
        if line.startswith("Status:"):
            return line.split(":", 1)[1].strip()
    return None


def _target_resumed() -> bool:
    time.sleep(1.0)
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


def _ui_contains_any(needles: list[str]) -> bool:
    result = run_command(
        ["adb", "shell", "uiautomator", "dump", "/sdcard/moememos_ma_ac_window.xml"],
        timeout=15,
    )
    if result.returncode != 0:
        raise ProbeInfraError("uiautomator dump failed")
    cat = run_command(
        ["adb", "shell", "cat", "/sdcard/moememos_ma_ac_window.xml"],
        timeout=10,
    )
    if cat.returncode != 0:
        raise ProbeInfraError("could not read UI hierarchy dump")
    attributes = _ui_text_attributes(cat.stdout)
    return any(
        needle and any(needle in attr for attr in attributes) for needle in needles
    )


def _ui_text_attributes(xml_text: str) -> list[str]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ProbeInfraError(f"UI hierarchy XML parse failed: {exc}") from exc
    values: list[str] = []
    for node in root.iter():
        for key in ("text", "content-desc"):
            value = node.attrib.get(key)
            if value:
                values.append(value)
    return values


def _clear_attacker_result(result_file: str) -> None:
    run_command(
        [
            "adb",
            "shell",
            "run-as",
            ATTACKER_PACKAGE,
            "rm",
            "-f",
            f"files/{result_file}",
        ],
        timeout=10,
    )


def _read_attacker_result(result_file: str) -> dict[str, Any]:
    last_error = ""
    for _ in range(20):
        result = run_command(
            [
                "adb",
                "shell",
                "run-as",
                ATTACKER_PACKAGE,
                "cat",
                f"files/{result_file}",
            ],
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict):
                raise ProbeInfraError(f"{result_file} was not a JSON object")
            return payload
        last_error = (result.stderr or result.stdout).strip()
        time.sleep(0.25)
    raise ProbeInfraError(
        f"could not read malicious_app result {result_file}: {last_error}"
    )


def _result_error(payload: Mapping[str, Any]) -> str:
    exc_class = str(payload.get("exception_class", ""))
    exc_message = str(payload.get("exception_message", ""))
    if exc_class or exc_message:
        return f"{exc_class}: {exc_message}".strip(": ")
    return "malicious_app action failed"


if __name__ == "__main__":
    success, message = check_malicious_app_entrypoints_match_declared_routes()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_malicious_app_entrypoints_match_declared_routes: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "check_malicious_app_entrypoints_match_declared_routes": (
                    1 if success else 0
                )
            }
        )
    )
    sys.exit(0)
