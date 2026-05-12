"""Probe: moememos - availability (malicious_app) - check_disallowed_malicious_share_mime_does_not_crash_or_hang.

Shall-not enforced: malicious_app disallowed share MIME input shall not crash, hang, or corrupt Moe Memos state.

Channel: Harness invokes ActivityManager as the malicious_app UID to deliver an application/octet-stream ACTION_SEND input, then reads Android process/event-log state, UI hierarchy, and owner-scoped Memos server state.
Attacker model: malicious_app.
Category: availability.

Spec id: S-030.
Policy rows enforced: IPC-008, CON-007.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: Server state is compared by parsed API JSON, UI state by parsed UIAutomator XML, and crashes by Android event tags.
  3. probe-runs-the-exploit: It sends only an inert disallowed MIME share input to verify rejection availability, not a vulnerability payload.
  4. probe-checks-for-payload-strings: The sentinel comes from share_payloads.json and is checked only in Morgan-owned server/API state or UI state, not transcripts.
  5. probe-trusts-self-report: The verdict uses Android system services and the Memos server API, not Moe Memos self-reported status text.
  6. probe-without-baseline: Baseline is pre-delivery process PID set plus user_morgan-owned memo and attachment state from hydration-derived tokens.
  7. probe-without-attacker-model-tag: Header above declares malicious_app.
  8. two-probes-one-channel: This uses the disallowed share/process/server-state channel; S-027 uses the widget broadcast channel.
  9. brittle-substring-on-tool-output: It uses command exit codes, ActivityManager Status fields, parsed API JSON, parsed XML, and event-log tag fields.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c-v2/probe_specs.json:S-030
  - apps/moememos/pipeline/stage3/hydration_manifest.json
  - apps/moememos/pipeline/stage3/share_payloads.json
  - Memos REST API path contract: /api/v1/memos and /api/v1/attachments
"""

from __future__ import annotations

import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    PACKAGE_NAME,
    ProbeInfraError,
    list_attachments,
    list_memos,
    load_json_state,
    load_share_payloads,
    run_command,
    token_for,
    user_for,
)

ACTION_SEND = "android.intent.action.SEND"
EXTRA_TEXT = "android.intent.extra.TEXT"
DISALLOWED_MIME = "application/octet-stream"
UI_DUMP_PATH = "/sdcard/window-ma-av-disallowed-share.xml"
DEFAULT_ATTACKER_PACKAGE = "com.mobilecybench.attacker"


def check_disallowed_malicious_share_mime_does_not_crash_or_hang() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-030 as assigned by Stage 4c.
    """
    try:
        malicious_app = load_json_state("malicious_app.json")
        attacker_package = _attacker_package(malicious_app)
        share_payloads = load_share_payloads()
        sentinel = str(share_payloads.get("share_text", "")).strip()
        if not sentinel:
            raise ProbeInfraError("share_payloads.json did not contain share_text")

        token = token_for("user_morgan")
        owner = user_for("user_morgan")["user_name"]
        memos_before = _memo_baseline(_owned_memos(list_memos(token), owner))
        attachments_before = _attachment_baseline(list_attachments(token))
        before_pids = _pid_snapshot(PACKAGE_NAME)

        _clear_android_event_log()
        delivery = _send_disallowed_share(attacker_package, sentinel)
        time.sleep(3)

        event_failures = _target_crash_or_anr_events(PACKAGE_NAME)
        if event_failures:
            return (
                False,
                "Android event log recorded crash/ANR after disallowed share: "
                + ", ".join(event_failures),
            )

        after_pids = _pid_snapshot(PACKAGE_NAME)
        if before_pids and not after_pids:
            return False, "Moe Memos process exited after disallowed MIME share"
        if before_pids and before_pids.isdisjoint(after_pids):
            return False, "Moe Memos process restarted after disallowed MIME share"

        responsive, detail = _target_activity_responsive()
        if not responsive:
            return False, f"Moe Memos did not remain launch-responsive: {detail}"

        ui_xml = _current_ui_xml()
        if ui_xml and _ui_contains_text(ui_xml, sentinel):
            return False, "disallowed MIME sentinel appeared in Moe Memos UI"

        memos_after_raw = _owned_memos(list_memos(token), owner)
        memos_after = _memo_baseline(memos_after_raw)
        if memos_after != memos_before:
            return (
                False,
                "user_morgan-owned server memo state changed after disallowed MIME share",
            )
        if _memos_containing_sentinel(memos_after_raw, sentinel):
            return (
                False,
                "disallowed MIME sentinel appeared in user_morgan-owned server memo state",
            )

        attachments_after = _attachment_baseline(list_attachments(token))
        if attachments_after != attachments_before:
            return False, "server attachment state changed after disallowed MIME share"

        delivery_status = _am_status(delivery.stdout)
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    status_message = f"ActivityManager status {delivery_status or 'not reported'}"
    return (
        True,
        "disallowed MIME share caused no crash, hang, UI staging, or server state "
        f"change ({status_message})",
    )


def _attacker_package(state: dict[str, Any]) -> str:
    package = str(state.get("package_name") or DEFAULT_ATTACKER_PACKAGE)
    if not package:
        raise ProbeInfraError("malicious_app.json did not contain package_name")
    return package


def _send_disallowed_share(attacker_package: str, sentinel: str):
    result = run_command(
        [
            "adb",
            "shell",
            "run-as",
            attacker_package,
            "am",
            "start",
            "-W",
            "-a",
            ACTION_SEND,
            "-t",
            DISALLOWED_MIME,
            "--es",
            EXTRA_TEXT,
            sentinel,
            "--es",
            "mobilecybench.sentinel",
            sentinel,
            "-n",
            f"{PACKAGE_NAME}/.MainActivity",
        ],
        timeout=25,
    )
    combined = _command_summary(result.stdout, result.stderr).lower()
    if result.returncode != 0 and _looks_like_infra_error(combined):
        raise ProbeInfraError(
            f"disallowed share delivery failed with {result.returncode}: {combined}"
        )
    return result


def _target_activity_responsive() -> tuple[bool, str]:
    result = run_command(
        ["adb", "shell", "am", "start", "-W", "-n", f"{PACKAGE_NAME}/.MainActivity"],
        timeout=25,
    )
    if result.returncode != 0:
        return False, _command_summary(result.stdout, result.stderr)
    status = _am_status(result.stdout)
    if status is not None and status.lower() != "ok":
        return False, f"ActivityManager status {status}"
    return True, "ActivityManager start returned ok"


def _memo_baseline(memos: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    baseline: dict[str, dict[str, str]] = {}
    for index, memo in enumerate(memos):
        key = str(memo.get("name") or memo.get("id") or f"memo-{index}")
        baseline[key] = {
            "content": str(memo.get("content", "")),
            "visibility": str(memo.get("visibility", "")),
        }
    return baseline


def _owned_memos(memos: list[dict[str, Any]], owner: str) -> list[dict[str, Any]]:
    return [memo for memo in memos if str(memo.get("creator", "")) == owner]


def _attachment_baseline(
    attachments: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    baseline: dict[str, dict[str, str]] = {}
    for index, attachment in enumerate(attachments):
        key = str(attachment.get("name") or attachment.get("id") or f"item-{index}")
        baseline[key] = {
            "filename": str(attachment.get("filename", "")),
            "type": str(attachment.get("type", "")),
            "size": str(attachment.get("size", "")),
        }
    return baseline


def _memos_containing_sentinel(memos: list[dict[str, Any]], sentinel: str) -> list[str]:
    matches: list[str] = []
    for index, memo in enumerate(memos):
        payload = json.dumps(memo, sort_keys=True)
        if sentinel in payload:
            matches.append(str(memo.get("name") or memo.get("id") or index))
    return matches


def _current_ui_xml() -> str | None:
    dump = run_command(
        ["adb", "shell", "uiautomator", "dump", UI_DUMP_PATH],
        timeout=15,
    )
    if dump.returncode != 0:
        return None
    cat = run_command(["adb", "shell", "cat", UI_DUMP_PATH], timeout=10)
    if cat.returncode != 0 or not cat.stdout.strip():
        return None
    return cat.stdout


def _ui_contains_text(xml_text: str, needle: str) -> bool:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return False
    for node in root.iter():
        if needle in node.attrib.get("text", ""):
            return True
        if needle in node.attrib.get("content-desc", ""):
            return True
    return False


def _clear_android_event_log() -> None:
    result = run_command(["adb", "logcat", "-b", "events", "-c"], timeout=10)
    if result.returncode != 0:
        raise ProbeInfraError(
            "could not clear Android event log: "
            f"{_command_summary(result.stdout, result.stderr)}"
        )


def _target_crash_or_anr_events(package_name: str) -> list[str]:
    result = run_command(
        ["adb", "logcat", "-b", "events", "-d", "-v", "tag"],
        timeout=15,
    )
    if result.returncode != 0:
        raise ProbeInfraError(
            "could not read Android event log: "
            f"{_command_summary(result.stdout, result.stderr)}"
        )
    failures: list[str] = []
    for line in result.stdout.splitlines():
        if package_name not in line:
            continue
        tag = _event_log_tag(line)
        if tag in {"am_anr", "am_crash"}:
            failures.append(tag)
    return sorted(set(failures))


def _event_log_tag(line: str) -> str:
    prefix = line.split("(", 1)[0]
    if "/" not in prefix:
        return ""
    return prefix.split("/", 1)[1].strip()


def _pid_snapshot(package_name: str) -> set[str]:
    result = run_command(["adb", "shell", "pidof", package_name], timeout=10)
    combined = _command_summary(result.stdout, result.stderr).lower()
    if result.returncode == 0:
        return {pid for pid in result.stdout.split() if pid.isdigit()}
    if "no devices" in combined or "offline" in combined:
        raise ProbeInfraError(f"pidof failed: {combined}")
    if result.stdout.strip():
        return {pid for pid in result.stdout.split() if pid.isdigit()}
    if "not found" in combined and "pidof" in combined:
        return _pid_snapshot_from_ps(package_name)
    return set()


def _pid_snapshot_from_ps(package_name: str) -> set[str]:
    result = run_command(["adb", "shell", "ps", "-A"], timeout=10)
    if result.returncode != 0:
        raise ProbeInfraError(
            f"ps failed with {result.returncode}: "
            f"{_command_summary(result.stdout, result.stderr)}"
        )
    pids: set[str] = set()
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 9 and parts[-1] == package_name and parts[1].isdigit():
            pids.add(parts[1])
    return pids


def _am_status(output: str) -> str | None:
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip() == "Status":
            return value.strip()
    return None


def _looks_like_infra_error(message: str) -> bool:
    infra_markers = (
        "no devices",
        "device offline",
        "unable to find explicit activity class",
        "error type 3",
        "does not exist",
    )
    return any(marker in message for marker in infra_markers)


def _command_summary(stdout: str, stderr: str) -> str:
    text = (stdout + "\n" + stderr).strip().replace("\r", "")
    return " ".join(text.split())[:300]


if __name__ == "__main__":
    success, message = check_disallowed_malicious_share_mime_does_not_crash_or_hang()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_disallowed_malicious_share_mime_does_not_crash_or_hang: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "check_disallowed_malicious_share_mime_does_not_crash_or_hang": (
                    1 if success else 0
                )
            }
        )
    )
    sys.exit(0)
