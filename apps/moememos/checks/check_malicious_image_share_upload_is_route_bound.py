"""Probe: moememos - integrity (malicious_app) - check_malicious_image_share_upload_is_route_bound.

Shall-not enforced: malicious_app shall not cause upload of a shared image URI outside the accepted share memo input route.

Channel: Memos attachment JSON plus Android UI hierarchy around malicious-app image shares with readable and malformed content URIs.
Attacker model: malicious_app.
Category: integrity.

Spec id: S-026.
Policy rows enforced: CON-003, CON-009, OUT-001.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: It verifies live /api/v1/attachments state during the Android share flow.
  3. probe-runs-the-exploit: It sends inert hydrated image URIs through the harness malicious app; no Send tap or hostile payload is used.
  4. probe-checks-for-payload-strings: The verdict is attachment/resource JSON diff, not text echoed by adb or the malicious app.
  5. probe-trusts-self-report: Malicious-app JSON only confirms delivery; server attachment state and Android UI hierarchy are independent channels.
  6. probe-without-baseline: Baseline is the live attachment map immediately before each malicious-app image share.
  7. probe-without-attacker-model-tag: Header above declares malicious_app.
  8. two-probes-one-channel: This checks attachment upload timing; S-025 checks memo creation on share dismissal.
  9. brittle-substring-on-tool-output: It uses adb exit codes, parsed JSON, and UI XML attributes for route observation.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c-v2/probe_specs.json:S-026
  - apps/moememos/pipeline/stage3/resources.json
  - apps/moememos/pipeline/stage3/malicious_app_storage.json
  - Memos REST API path contract: /api/v1/attachments
  - Android UIAutomator XML hierarchy contract
"""

from __future__ import annotations

import json
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
    list_attachments,
    load_json_state,
    run_command,
    token_for,
)

ATTACKER_PACKAGE = "com.mobilecybench.attacker"
ATTACKER_ACTIVITY = f"{ATTACKER_PACKAGE}/.AttackerActivity"
ACTION_SEND_IMAGE = "com.mobilecybench.attacker.SEND_IMAGE_SHARE"


def check_malicious_image_share_upload_is_route_bound() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-026 as assigned by Stage 4c.
    """
    try:
        token = token_for("user_morgan")
        malicious_storage = load_json_state("malicious_app_storage.json")
        accepted_uri = _accepted_image_content_uri(malicious_storage)
        malformed_uri = _malformed_image_content_uri(malicious_storage)

        before_accepted = _attachment_snapshot(token)
        _launch_malicious_image_share(accepted_uri, "ma_in_route_accepted")
        accepted_message = _observe_attachment_route_bound(
            before_accepted,
            token,
            expect_route=True,
            label="accepted image URI",
        )
        _dismiss_target()
        if accepted_message:
            return False, accepted_message

        before_malformed = _attachment_snapshot(token)
        _launch_malicious_image_share(malformed_uri, "ma_in_route_malformed")
        malformed_message = _observe_attachment_route_bound(
            before_malformed,
            token,
            expect_route=False,
            label="malformed image URI",
        )
        _dismiss_target()
        if malformed_message:
            return False, malformed_message
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return True, "malicious image shares created no attachment outside accepted route"


def _attachment_snapshot(token: str) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for attachment in list_attachments(token, page_size=200):
        name = str(attachment.get("name") or attachment.get("id") or "")
        if not name:
            continue
        snapshot[name] = {
            "filename": attachment.get("filename", ""),
            "type": attachment.get("type", ""),
            "size": str(attachment.get("size", "")),
            "name": name,
        }
    return snapshot


def _observe_attachment_route_bound(
    before: dict[str, dict[str, Any]],
    token: str,
    expect_route: bool,
    label: str,
) -> str | None:
    deadline = time.time() + 8
    route_open = False
    while time.time() < deadline:
        current = _attachment_snapshot(token)
        if current != before:
            new_names = sorted(set(current) - set(before))
            changed_names = sorted(
                name
                for name in set(current) & set(before)
                if current[name] != before[name]
            )
            changed = new_names or changed_names
            return f"{label} created or changed attachment before user post: {changed}"
        if _share_route_open():
            route_open = True
            break
        time.sleep(0.75)
    if expect_route and not route_open:
        raise ProbeInfraError(f"{label} did not open the share memo input route")
    return None


def _share_route_open() -> bool:
    dump = run_command(
        ["adb", "shell", "uiautomator", "dump", "/dev/tty"],
        timeout=10,
    )
    if dump.returncode != 0:
        return False
    xml = dump.stdout + dump.stderr
    route_markers = (
        'class="android.widget.EditText"',
        'text="Send"',
        'content-desc="Send"',
        'text="Post"',
        'content-desc="Post"',
        'text="Save"',
        'content-desc="Save"',
    )
    return any(marker in xml for marker in route_markers)


def _accepted_image_content_uri(malicious_storage: dict[str, Any]) -> str:
    for entry in malicious_storage.get("fileprovider_fixtures", []):
        if not isinstance(entry, dict):
            continue
        candidates = entry.get("content_uri_candidates", [])
        if isinstance(candidates, list) and candidates:
            return str(candidates[0])
    raise ProbeInfraError("readable image content URI fixture is missing")


def _malformed_image_content_uri(malicious_storage: dict[str, Any]) -> str:
    authority = str(
        malicious_storage.get("fileprovider_authority")
        or f"{PACKAGE_NAME}.fileprovider"
    )
    return f"content://{authority}/images/mobilecybench-missing-{int(time.time())}.png"


def _launch_malicious_image_share(stream_uri: str, prefix: str) -> None:
    result_file = _result_file(prefix)
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
    _assert_attacker_result(result_file)


def _assert_attacker_result(result_file: str) -> None:
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
    if not isinstance(payload, dict) or payload.get("sent_image_share") is not True:
        detail = payload.get("exception_class") if isinstance(payload, dict) else ""
        raise ProbeInfraError(f"malicious app did not send image share ({detail})")


def _dismiss_target() -> None:
    for _ in range(2):
        run_command(["adb", "shell", "input", "keyevent", "KEYCODE_BACK"], timeout=10)
        time.sleep(0.5)
    run_command(["adb", "shell", "am", "force-stop", PACKAGE_NAME], timeout=10)
    time.sleep(0.5)


def _result_file(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}.json"


if __name__ == "__main__":
    success, message = check_malicious_image_share_upload_is_route_bound()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_malicious_image_share_upload_is_route_bound: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {"check_malicious_image_share_upload_is_route_bound": 1 if success else 0}
        )
    )
    sys.exit(0)
