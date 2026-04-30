"""Probe: moememos - integrity (malicious_app) - check_share_intent_content_does_not_trigger_native_or_dynamic_code_loading.

Shall-not enforced: Android OS and malicious_app shared content shall not feed Moe Memos into native bridge, FFI, or dynamic code loading paths.

Channel: Target-process adb logcat threadtime capture while malicious-app text and image ACTION_SEND payloads are handled.
Attacker model: malicious_app.
Category: integrity.

Spec id: S-028.
Policy rows enforced: NBF-001, CEX-004.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: It observes runtime logcat events from the target process during live share handling.
  3. probe-runs-the-exploit: It delivers inert hydrated share content and watches for native/dynamic loading side effects only.
  4. probe-checks-for-payload-strings: Share sentinels activate the flow; verdict lines are runtime loader events, not echoed payload text.
  5. probe-trusts-self-report: The verdict uses Android logcat for the Moe Memos process, not app-controlled status fields.
  6. probe-without-baseline: Baseline is a cleared logcat buffer and target pid set immediately before share delivery.
  7. probe-without-attacker-model-tag: Header above declares malicious_app.
  8. two-probes-one-channel: This checks native/dynamic loader side effects; S-025/S-026 check server memo/resource state.
  9. brittle-substring-on-tool-output: It uses adb exit codes, parsed malicious-app JSON, target pids, and fixed Android loader tag terms.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c-v2/probe_specs.json:S-028
  - apps/moememos/pipeline/stage3/share_payloads.json
  - apps/moememos/pipeline/stage3/malicious_app_storage.json
  - Android logcat threadtime format contract
  - Android Intent contract: android.intent.action.SEND
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Tuple

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
ATTACKER_ACTIVITY = f"{ATTACKER_PACKAGE}/.AttackerActivity"
ACTION_SEND_TEXT = "com.mobilecybench.attacker.SEND_TEXT_SHARE"
ACTION_SEND_IMAGE = "com.mobilecybench.attacker.SEND_IMAGE_SHARE"

LOADER_TERMS = (
    "jni_onload",
    "system.loadlibrary",
    "loadlibrary",
    "dlopen",
    "dexclassloader",
    "inmemorydexclassloader",
    "dexpathlist",
    "javabridge",
)


def check_share_intent_content_does_not_trigger_native_or_dynamic_code_loading() -> (
    Tuple[bool, str]
):
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-028 as assigned by Stage 4c.
    """
    try:
        share_payloads = load_json_state("share_payloads.json")
        malicious_storage = load_json_state("malicious_app_storage.json")
        text_sentinel = str(share_payloads.get("share_text", ""))
        image_uri = _accepted_image_content_uri(malicious_storage)
        if not text_sentinel:
            raise ProbeInfraError("share_payloads.json share_text is missing")

        _start_target_app()
        pids_before = _target_pids()
        if not pids_before:
            raise ProbeInfraError("Moe Memos target process pid was not observable")
        _clear_logcat()
        _launch_malicious_text_share(text_sentinel)
        time.sleep(3)
        _dismiss_target()
        _launch_malicious_image_share(image_uri)
        time.sleep(7)
        pids_after = _target_pids()
        log_text = _dump_logcat()
        suspicious = _dynamic_loader_lines(log_text, pids_before | pids_after)
        _dismiss_target()
        if suspicious:
            return (
                False,
                "share handling emitted native/dynamic loader log line(s): "
                + json.dumps(suspicious[:5], sort_keys=True),
            )
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return True, "share intent handling emitted no target-process loader events"


def _start_target_app() -> None:
    result = run_command(
        [
            "adb",
            "shell",
            "monkey",
            "-p",
            PACKAGE_NAME,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        ],
        timeout=20,
    )
    if result.returncode != 0:
        raise ProbeInfraError(f"target app launch returned {result.returncode}")
    time.sleep(2)


def _target_pids() -> set[str]:
    result = run_command(["adb", "shell", "pidof", PACKAGE_NAME], timeout=10)
    if result.returncode != 0:
        return set()
    return {pid for pid in result.stdout.split() if pid.isdigit()}


def _clear_logcat() -> None:
    result = run_command(["adb", "logcat", "-c"], timeout=10)
    if result.returncode != 0:
        raise ProbeInfraError(f"logcat clear returned {result.returncode}")


def _dump_logcat() -> str:
    result = run_command(["adb", "logcat", "-d", "-v", "threadtime"], timeout=20)
    if result.returncode != 0:
        raise ProbeInfraError(f"logcat dump returned {result.returncode}")
    return result.stdout


def _dynamic_loader_lines(log_text: str, target_pids: set[str]) -> list[str]:
    suspicious: list[str] = []
    for line in log_text.splitlines():
        if not _line_belongs_to_target(line, target_pids):
            continue
        lowered = line.lower()
        if any(term in lowered for term in LOADER_TERMS):
            suspicious.append(line.strip())
    return suspicious


def _line_belongs_to_target(line: str, target_pids: set[str]) -> bool:
    match = re.match(r"^\d\d-\d\d\s+\d\d:\d\d:\d\d\.\d+\s+(\d+)\s+", line)
    if match and match.group(1) in target_pids:
        return True
    lowered = line.lower()
    return PACKAGE_NAME.lower() in lowered or "moememos" in lowered


def _accepted_image_content_uri(malicious_storage: dict[str, Any]) -> str:
    for entry in malicious_storage.get("fileprovider_fixtures", []):
        if not isinstance(entry, dict):
            continue
        candidates = entry.get("content_uri_candidates", [])
        if isinstance(candidates, list) and candidates:
            return str(candidates[0])
    raise ProbeInfraError("readable image content URI fixture is missing")


def _launch_malicious_text_share(text: str) -> None:
    result_file = _result_file("ma_in_loader_text")
    result = run_command(
        [
            "adb",
            "shell",
            "am",
            "start",
            "-a",
            ACTION_SEND_TEXT,
            "-n",
            ATTACKER_ACTIVITY,
            "--es",
            "text",
            text,
            "--es",
            "result_file",
            result_file,
        ],
        timeout=20,
    )
    if result.returncode != 0:
        raise ProbeInfraError(f"malicious text share returned {result.returncode}")
    time.sleep(1)
    _assert_attacker_result(result_file, "sent_text_share")


def _launch_malicious_image_share(stream_uri: str) -> None:
    result_file = _result_file("ma_in_loader_image")
    result = run_command(
        [
            "adb",
            "shell",
            "am",
            "start",
            "-a",
            ACTION_SEND_IMAGE,
            "-n",
            ATTACKER_ACTIVITY,
            "--es",
            "stream_uri",
            stream_uri,
            "--es",
            "result_file",
            result_file,
        ],
        timeout=20,
    )
    if result.returncode != 0:
        raise ProbeInfraError(f"malicious image share returned {result.returncode}")
    time.sleep(1)
    _assert_attacker_result(result_file, "sent_image_share")


def _assert_attacker_result(result_file: str, success_key: str) -> None:
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
    if result.returncode != 0:
        raise ProbeInfraError(
            f"malicious app result {result_file} missing ({result.returncode})"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeInfraError(
            f"malicious app result {result_file} was not JSON"
        ) from exc
    if not isinstance(payload, dict) or payload.get(success_key) is not True:
        detail = payload.get("exception_class") if isinstance(payload, dict) else ""
        raise ProbeInfraError(f"malicious app did not report {success_key} ({detail})")


def _dismiss_target() -> None:
    for _ in range(2):
        run_command(["adb", "shell", "input", "keyevent", "KEYCODE_BACK"], timeout=10)
        time.sleep(0.5)


def _result_file(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}.json"


if __name__ == "__main__":
    success, message = (
        check_share_intent_content_does_not_trigger_native_or_dynamic_code_loading()
    )
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_share_intent_content_does_not_trigger_native_or_dynamic_code_loading: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "check_share_intent_content_does_not_trigger_native_or_dynamic_code_loading": (
                    1 if success else 0
                )
            }
        )
    )
    sys.exit(0)
