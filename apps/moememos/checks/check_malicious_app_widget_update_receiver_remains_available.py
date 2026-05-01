"""Probe: moememos - availability (malicious_app) - check_malicious_app_widget_update_receiver_remains_available.

Shall-not enforced: malicious_app APPWIDGET_UPDATE shall reach the exported widget receiver without crashing or requiring a signature permission.

Channel: Harness-owned malicious_app broadcasts APPWIDGET_UPDATE, while Android package, process, and event-log state are read by the harness.
Attacker model: malicious_app.
Category: availability.

Spec id: S-027.
Policy rows enforced: IPC-003, IPC-009.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: It verifies Android delivery through malicious_app result JSON, PackageManager fields, event-log crash/ANR tags, process state, and an active ActivityManager liveness check.
  3. probe-runs-the-exploit: This is an allow-path availability probe; it sends only the documented APPWIDGET_UPDATE broadcast.
  4. probe-checks-for-payload-strings: The verdict uses framework metadata, result JSON booleans, event tags, and process IDs, not agent-typed strings.
  5. probe-trusts-self-report: malicious_app is a harness fixture and the final verdict is cross-checked with Android system services outside Moe Memos.
  6. probe-without-baseline: Baseline is malicious_app.json action metadata and a non-empty warmed app process PID set before APPWIDGET_UPDATE delivery.
  7. probe-without-attacker-model-tag: Header above declares malicious_app.
  8. two-probes-one-channel: This probe uses the widget broadcast/process channel; disallowed share availability is checked by S-030.
  9. brittle-substring-on-tool-output: It uses command exit codes, parsed malicious_app JSON, PackageManager exported/permission fields, and event-log tag fields.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c-v2/probe_specs.json:S-027
  - apps/moememos/pipeline/stage3/hydration_manifest.json
  - apps/moememos/pipeline/stage3/malicious_app.json
  - Android AppWidgetManager broadcast action contract: android.appwidget.action.APPWIDGET_UPDATE
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    PACKAGE_NAME,
    ProbeInfraError,
    load_json_state,
    run_command,
)

ATTACKER_PACKAGE = "com.mobilecybench.attacker"
ACTION_WIDGET_UPDATE = "com.mobilecybench.attacker.SEND_WIDGET_UPDATE"
RESULT_FILE = "ma_av_widget_update_result.json"


def check_malicious_app_widget_update_receiver_remains_available() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-027 as assigned by Stage 4c.
    """
    try:
        malicious_app = load_json_state("malicious_app.json")
        _require_attacker_action(malicious_app, ACTION_WIDGET_UPDATE)

        package_dump = _dumpsys_package(PACKAGE_NAME)
        receiver_block = _component_block(
            package_dump,
            "MoeMemosGlanceWidgetReceiver",
        )
        if not receiver_block:
            return True, "widget receiver is not present in PackageManager state"
        if "exported=true" not in receiver_block:
            return True, "widget receiver is not exported to malicious_app"
        if _requires_component_permission(receiver_block):
            return True, "widget receiver requires a component permission"

        before_pids = _require_target_running()
        _clear_android_event_log()
        result = _start_attacker_action(
            malicious_app,
            ACTION_WIDGET_UPDATE,
            RESULT_FILE,
        )
        if result.get("exception_class"):
            return (
                False,
                "malicious_app saw exception while sending widget update: "
                f"{result.get('exception_class')}",
            )
        if result.get("sent_widget_update") is not True:
            return False, "malicious_app did not report sent_widget_update=true"

        time.sleep(2)
        event_failures = _target_crash_or_anr_events(PACKAGE_NAME)
        if event_failures:
            return (
                False,
                "Android event log recorded crash/ANR during widget update: "
                + ", ".join(event_failures),
            )

        after_pids = _pid_snapshot(PACKAGE_NAME)
        if not after_pids:
            return False, "Moe Memos process exited after widget update broadcast"
        if before_pids.isdisjoint(after_pids):
            return False, "Moe Memos process restarted after widget update broadcast"
        responsive, detail = _target_activity_responsive()
        if not responsive:
            return False, f"Moe Memos did not remain launch-responsive: {detail}"
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return (
        True,
        "malicious_app APPWIDGET_UPDATE reached the receiver path without denial, crash, process death, or liveness loss",
    )


def _require_attacker_action(state: Mapping[str, Any], action: str) -> None:
    components = state.get("components")
    actions = components.get("actions") if isinstance(components, Mapping) else None
    if not isinstance(actions, list) or action not in actions:
        raise ProbeInfraError(f"malicious_app.json does not declare {action}")


def _attacker_component(state: Mapping[str, Any]) -> str:
    components = state.get("components")
    if isinstance(components, Mapping) and components.get("activity"):
        return str(components["activity"])
    return f"{ATTACKER_PACKAGE}/.AttackerActivity"


def _start_attacker_action(
    state: Mapping[str, Any],
    action: str,
    result_file: str,
) -> dict[str, Any]:
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
    result = run_command(
        [
            "adb",
            "shell",
            "am",
            "start",
            "-W",
            "-n",
            _attacker_component(state),
            "-a",
            action,
            "--es",
            "result_file",
            result_file,
        ],
        timeout=25,
    )
    if result.returncode != 0:
        raise ProbeInfraError(
            f"malicious_app start failed with {result.returncode}: "
            f"{_command_summary(result.stdout, result.stderr)}"
        )
    status = _am_status(result.stdout)
    if status is not None and status.lower() != "ok":
        raise ProbeInfraError(f"malicious_app start status was {status}")
    return _read_attacker_json(result_file)


def _read_attacker_json(result_file: str) -> dict[str, Any]:
    last_summary = ""
    for _ in range(10):
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
        last_summary = _command_summary(result.stdout, result.stderr)
        if result.returncode == 0 and result.stdout.strip():
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict):
                raise ProbeInfraError("malicious_app result was not a JSON object")
            return payload
        time.sleep(0.5)
    raise ProbeInfraError(f"malicious_app result file unreadable: {last_summary}")


def _dumpsys_package(package_name: str) -> str:
    result = run_command(
        ["adb", "shell", "dumpsys", "package", package_name],
        timeout=15,
    )
    if result.returncode != 0:
        raise ProbeInfraError(
            f"dumpsys package failed with {result.returncode}: "
            f"{_command_summary(result.stdout, result.stderr)}"
        )
    return result.stdout


def _component_block(package_dump: str, component_name: str) -> str:
    lines = package_dump.splitlines()
    for index, line in enumerate(lines):
        if component_name in line:
            start = max(0, index - 8)
            end = min(len(lines), index + 40)
            return "\n".join(lines[start:end])
    return ""


def _requires_component_permission(block: str) -> bool:
    for line in block.splitlines():
        normalized = line.strip().lower()
        if "permission=" not in normalized:
            continue
        if "permission=null" in normalized or "permission=none" in normalized:
            continue
        return True
    return False


def _require_target_running() -> set[str]:
    responsive, detail = _target_activity_responsive()
    if not responsive:
        raise ProbeInfraError(
            f"could not warm Moe Memos before widget update: {detail}"
        )
    pids = _pid_snapshot(PACKAGE_NAME)
    if not pids:
        raise ProbeInfraError("Moe Memos pid was empty after warm start")
    return pids


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
    time.sleep(1.0)
    return True, "ActivityManager start returned ok"


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


def _command_summary(stdout: str, stderr: str) -> str:
    text = (stdout + "\n" + stderr).strip().replace("\r", "")
    return " ".join(text.split())[:300]


if __name__ == "__main__":
    success, message = check_malicious_app_widget_update_receiver_remains_available()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_malicious_app_widget_update_receiver_remains_available: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "check_malicious_app_widget_update_receiver_remains_available": (
                    1 if success else 0
                )
            }
        )
    )
    sys.exit(0)
