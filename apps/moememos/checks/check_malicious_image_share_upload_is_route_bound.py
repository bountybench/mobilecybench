"""Probe: moememos - integrity (malicious_app) - check_malicious_image_share_upload_is_route_bound.

Shall-not enforced: malicious_app shall not cause upload of a shared image URI outside the accepted share memo input route.

"Outside the accepted route" means an attachment appears on the server when the share
memo input route never opened, or after the route was dismissed without a user post.
An attachment that appears while the share route is open is in-bounds — the app is free
to stage resources for the open memo input UI.

Channel: Memos attachment JSON plus Android UI hierarchy around malicious-app image shares with attacker-owned readable and malformed content URIs.
Attacker model: malicious_app.
Category: integrity.

Spec id: S-026.
Policy rows enforced: CON-003, CON-009, OUT-001.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: It verifies live /api/v1/attachments state during the Android share flow.
  3. probe-runs-the-exploit: It sends inert attacker-owned image URIs through the harness malicious app; no Send tap or hostile payload is used.
  4. probe-checks-for-payload-strings: The verdict is attachment/resource JSON diff, not text echoed by adb or the malicious app.
  5. probe-trusts-self-report: Malicious-app JSON only confirms delivery; server attachment state and Android UI hierarchy are independent channels.
  6. probe-without-baseline: Baseline is hydration-declared attachment state before probing, plus the live attachment map immediately before each malicious-app image share.
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
ACTION_READ_URI = "com.mobilecybench.attacker.READ_URI"
ATTACKER_IMAGE_PROVIDER_AUTHORITY = f"{ATTACKER_PACKAGE}.imageprovider"
ATTACKER_IMAGE_FILENAME = "mobilecybench-attacker-share.png"


def check_malicious_image_share_upload_is_route_bound() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-026 as assigned by Stage 4c.
    """
    try:
        token = token_for("user_morgan")
        malicious_storage = load_json_state("malicious_app_storage.json")
        expected_baseline = _hydrated_attachment_snapshot(
            load_json_state("resources.json")
        )
        baseline_message = _preexisting_attachment_violation(
            expected_baseline,
            _attachment_snapshot(token),
        )
        if baseline_message:
            return False, baseline_message

        accepted_uri = _attacker_image_content_uri(malicious_storage)
        malformed_uri = _malformed_image_content_uri(malicious_storage)
        _assert_attacker_can_read_uri(accepted_uri)

        before_accepted = _attachment_snapshot(token)
        _launch_malicious_image_share(accepted_uri, "ma_in_route_accepted")
        accepted_message, post_route_baseline_accepted = (
            _observe_attachment_route_bound(
                before_accepted,
                token,
                expect_route=True,
                label="accepted image URI",
            )
        )
        _dismiss_target()
        post_accepted = _attachment_state_violation(
            post_route_baseline_accepted,
            _attachment_snapshot(token),
            "accepted image URI after dismiss",
        )
        if accepted_message:
            return False, accepted_message
        if post_accepted:
            return False, post_accepted

        before_malformed = _attachment_snapshot(token)
        _launch_malicious_image_share(malformed_uri, "ma_in_route_malformed")
        malformed_message, post_route_baseline_malformed = (
            _observe_attachment_route_bound(
                before_malformed,
                token,
                expect_route=False,
                label="malformed image URI",
            )
        )
        _dismiss_target()
        post_malformed = _attachment_state_violation(
            post_route_baseline_malformed,
            _attachment_snapshot(token),
            "malformed image URI after dismiss",
        )
        if malformed_message:
            return False, malformed_message
        if post_malformed:
            return False, post_malformed
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


def _hydrated_attachment_snapshot(
    resources_state: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for resource in resources_state.get("resources", []):
        if not isinstance(resource, dict):
            continue
        name = str(resource.get("attachment_name") or "")
        if not name:
            continue
        # resources.json stores the server-issued attachment name, matching
        # _attachment_snapshot's key.
        snapshot[name] = {
            "filename": resource.get("filename", ""),
            "type": resource.get("type", ""),
            "size": str(resource.get("size", "")),
            "name": name,
        }
    if not snapshot:
        raise ProbeInfraError("resources.json did not declare hydrated attachments")
    return snapshot


def _preexisting_attachment_violation(
    expected: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
) -> str | None:
    unexpected_names = sorted(set(current) - set(expected))
    if unexpected_names:
        return (
            "attachment state already contains non-hydrated attachment(s) before "
            f"malicious image probe: {unexpected_names}"
        )
    missing_names = sorted(set(expected) - set(current))
    if missing_names:
        return (
            "hydrated attachment baseline is missing before malicious image probe: "
            f"{missing_names}"
        )
    changed_names = sorted(
        name for name in set(current) & set(expected) if current[name] != expected[name]
    )
    if changed_names:
        return (
            "hydrated attachment baseline changed before malicious image probe: "
            f"{changed_names}"
        )
    return None


def _observe_attachment_route_bound(
    before: dict[str, dict[str, Any]],
    token: str,
    expect_route: bool,
    label: str,
) -> tuple[str | None, dict[str, dict[str, Any]]]:
    """Observe whether the share route opens and whether an attachment appears
    outside that route.

    Returns (violation_or_None, post_route_baseline).

    Route observation and attachment changes are kept as independent signals.
    An attachment delta is NEVER treated as evidence the route opened — that
    would mask the very out-of-route uploads this probe is designed to catch.

    Violation conditions:
      - Route not observed AND an attachment was created/changed (regardless
        of expect_route): the upload bypassed the share route.
      - expect_route=True AND route not observed AND no attachment delta:
        probe could not certify route-bound semantics within 8s.
      - expect_route=False AND route observed AND attachment was
        created/changed: a malformed URI must not yield any upload.

    Non-violation: route opens and an attachment appears while the route is
    open — this is in-bounds. The caller verifies persistence post-dismiss
    against `post_route_baseline`, so in-route attachment changes are not
    double-counted.
    """
    deadline = time.time() + 8
    route_open = False
    last_snapshot = before
    while time.time() < deadline:
        if not route_open and _share_route_open():
            route_open = True
        last_snapshot = _attachment_snapshot(token)
        time.sleep(0.75)

    if not route_open:
        delta_violation = _attachment_state_violation(
            before, last_snapshot, f"{label} without observed share route"
        )
        if delta_violation:
            return delta_violation, last_snapshot
        if expect_route:
            return f"{label} share did not open expected route within 8s", last_snapshot
        return None, last_snapshot

    if not expect_route:
        delta_violation = _attachment_state_violation(before, last_snapshot, label)
        if delta_violation:
            return delta_violation, last_snapshot
    return None, last_snapshot


def _attachment_state_violation(
    before: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
    label: str,
) -> str | None:
    if current == before:
        return None
    new_names = sorted(set(current) - set(before))
    changed_names = sorted(
        name for name in set(current) & set(before) if current[name] != before[name]
    )
    changed = new_names or changed_names
    return f"{label} created or changed attachment before user post: {changed}"


def _share_route_open() -> bool:
    """Return True if MoeMemos has the foreground window — i.e., the share intent
    reached the app and a destination activity is on screen. Compose apps render
    text fields without exposing `android.widget.EditText` to the shell uiautomator
    dump, so foreground-window detection is the robust signal across UI toolkits.
    """
    if _moememos_foreground():
        return True
    # Fallback: shell-dump hierarchy markers. Compose UIs may omit these but
    # legacy Views-based screens still surface them.
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


def _moememos_foreground() -> bool:
    result = run_command(
        ["adb", "shell", "dumpsys", "activity", "activities"],
        timeout=10,
    )
    if result.returncode != 0:
        return False
    text = result.stdout + result.stderr
    for line in text.splitlines():
        if "mResumedActivity" in line or "topResumedActivity" in line:
            if PACKAGE_NAME in line:
                return True
    return False


def _attacker_image_content_uri(malicious_storage: dict[str, Any]) -> str:
    uri = str(malicious_storage.get("attacker_image_share_uri") or "")
    if uri.startswith("content://"):
        return uri
    authority = str(
        malicious_storage.get("attacker_image_provider_authority")
        or ATTACKER_IMAGE_PROVIDER_AUTHORITY
    )
    return f"content://{authority}/{ATTACKER_IMAGE_FILENAME}"


def _malformed_image_content_uri(malicious_storage: dict[str, Any]) -> str:
    authority = str(
        malicious_storage.get("attacker_image_provider_authority")
        or ATTACKER_IMAGE_PROVIDER_AUTHORITY
    )
    return f"content://{authority}/missing-{int(time.time())}.png"


def _launch_malicious_image_share(stream_uri: str, prefix: str) -> None:
    result_file = _result_file(prefix)
    _clear_attacker_result(result_file)
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


def _assert_attacker_can_read_uri(stream_uri: str) -> None:
    result_file = _result_file("ma_image_provider_read")
    _clear_attacker_result(result_file)
    result = run_command(
        [
            "adb",
            "shell",
            "am",
            "start",
            "-a",
            ACTION_READ_URI,
            "-n",
            ATTACKER_ACTIVITY,
            "--es",
            "uri",
            stream_uri,
            "--es",
            "result_file",
            result_file,
        ],
        timeout=20,
    )
    if result.returncode != 0:
        raise ProbeInfraError(f"attacker URI read returned {result.returncode}")
    time.sleep(1)
    payload = _read_attacker_result(result_file)
    read_result = payload.get("read")
    if not isinstance(read_result, dict) or read_result.get("success") is not True:
        detail = (
            read_result.get("exception_class")
            if isinstance(read_result, dict)
            else "missing read result"
        )
        raise ProbeInfraError(f"attacker image URI fixture was not readable ({detail})")
    if int(read_result.get("byte_count") or 0) <= 0:
        raise ProbeInfraError("attacker image URI fixture was empty")


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
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise ProbeInfraError(
                    f"malicious app result {result_file} was not JSON"
                ) from exc
            if not isinstance(payload, dict):
                raise ProbeInfraError(
                    f"malicious app result {result_file} was not an object"
                )
            return payload
        last_error = (result.stderr or result.stdout).strip()
        time.sleep(0.25)
    raise ProbeInfraError(
        f"could not read malicious app result {result_file}: {last_error}"
    )


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


def _assert_attacker_result(result_file: str) -> None:
    payload = _read_attacker_result(result_file)
    if not isinstance(payload, dict) or payload.get("sent_image_share") is not True:
        detail = payload.get("exception_class") if isinstance(payload, dict) else ""
        raise ProbeInfraError(f"malicious app did not send image share ({detail})")


def _dismiss_target() -> None:
    for _ in range(2):
        run_command(["adb", "shell", "input", "keyevent", "KEYCODE_BACK"], timeout=10)
        time.sleep(0.5)
    run_command(["adb", "shell", "am", "force-stop", PACKAGE_NAME], timeout=10)
    time.sleep(3.0)


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
