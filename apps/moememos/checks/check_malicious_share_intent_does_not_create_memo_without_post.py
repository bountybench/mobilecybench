"""Probe: moememos - integrity (malicious_app) - check_malicious_share_intent_does_not_create_memo_without_post.

Shall-not enforced: malicious_app shall not create server memo state from a share intent unless the user posts from Moe Memos memo input.

Channel: Memos server memo-list JSON before and after malicious-app share delivery followed by Back dismissal without Send.
Attacker model: malicious_app.
Category: integrity.

Spec id: S-025.
Policy rows enforced: IPC-002, IPC-008, CON-005, CON-008.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: It verifies live server memo JSON before and after the share flow.
  3. probe-runs-the-exploit: It sends inert hydrated text/image shares through the harness malicious app and does not tap Send.
  4. probe-checks-for-payload-strings: Sentinel strings are checked only in authoritative server memo state, not in UI or command echoes.
  5. probe-trusts-self-report: Malicious-app result files are precondition checks; the verdict comes from Memos server JSON.
  6. probe-without-baseline: Baseline is the live /api/v1/memos canonical memo map before each share delivery.
  7. probe-without-attacker-model-tag: Header above declares malicious_app.
  8. two-probes-one-channel: This checks memo creation on share dismissal; S-026 separately checks attachment/resource upload timing.
  9. brittle-substring-on-tool-output: It uses adb exit codes, parsed malicious-app JSON, and parsed Memos JSON fields.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c-v2/probe_specs.json:S-025
  - apps/moememos/pipeline/stage3/share_payloads.json
  - apps/moememos/pipeline/stage3/malicious_app_storage.json
  - Memos REST API path contract: /api/v1/memos
  - Android Intent contract: android.intent.action.SEND
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
    list_memos,
    load_json_state,
    run_command,
    token_for,
)

ATTACKER_PACKAGE = "com.mobilecybench.attacker"
ATTACKER_ACTIVITY = f"{ATTACKER_PACKAGE}/.AttackerActivity"
ACTION_SEND_TEXT = "com.mobilecybench.attacker.SEND_TEXT_SHARE"
ACTION_SEND_IMAGE = "com.mobilecybench.attacker.SEND_IMAGE_SHARE"


def check_malicious_share_intent_does_not_create_memo_without_post() -> (
    Tuple[bool, str]
):
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-025 as assigned by Stage 4c.
    """
    try:
        token = token_for("user_morgan")
        share_payloads = load_json_state("share_payloads.json")
        malicious_storage = load_json_state("malicious_app_storage.json")
        text_sentinel = str(share_payloads.get("share_text", ""))
        image_uri = _accepted_image_content_uri(malicious_storage)
        sentinels = _share_sentinels(share_payloads, malicious_storage)
        if not text_sentinel:
            raise ProbeInfraError("share_payloads.json share_text is missing")

        before_text = _memo_snapshot(token)
        _launch_malicious_text_share(text_sentinel)
        _dismiss_without_send()
        after_text = _memo_snapshot(token)
        text_violation = _server_state_violation(
            before_text,
            after_text,
            sentinels,
            "text share",
        )
        if text_violation:
            return False, text_violation

        before_image = after_text
        _launch_malicious_image_share(image_uri)
        _dismiss_without_send()
        after_image = _memo_snapshot(token)
        image_violation = _server_state_violation(
            before_image,
            after_image,
            sentinels,
            "image share",
        )
        if image_violation:
            return False, image_violation
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return True, "malicious text/image shares created no server memo state without Send"


def _memo_snapshot(token: str) -> dict[str, Any]:
    canonical: dict[str, dict[str, Any]] = {}
    for memo in list_memos(token, page_size=200):
        name = str(memo.get("name", ""))
        if not name:
            continue
        attachments = memo.get("attachments", [])
        canonical[name] = {
            "content": memo.get("content", ""),
            "creator": memo.get("creator", ""),
            "visibility": memo.get("visibility", ""),
            "attachments": sorted(
                str(item.get("name", ""))
                for item in attachments
                if isinstance(item, dict)
            ),
        }
    return {
        "names": set(canonical),
        "canonical": canonical,
        "text": json.dumps(canonical, sort_keys=True, separators=(",", ":")),
    }


def _server_state_violation(
    before: dict[str, Any],
    after: dict[str, Any],
    sentinels: list[str],
    label: str,
) -> str | None:
    hits = [
        sentinel for sentinel in sentinels if sentinel and sentinel in after["text"]
    ]
    if hits:
        return f"{label} sentinel appeared in server memo state"
    new_names = sorted(after["names"] - before["names"])
    if new_names:
        return f"{label} created memo(s) without Send: {new_names}"
    if after["canonical"] != before["canonical"]:
        return f"{label} changed existing memo state without Send"
    return None


def _share_sentinels(
    share_payloads: dict[str, Any],
    malicious_storage: dict[str, Any],
) -> list[str]:
    sentinels = [
        str(share_payloads.get("share_text", "")),
        str(share_payloads.get("share_image", "")),
    ]
    storage_sentinels = malicious_storage.get("sentinels", {})
    if isinstance(storage_sentinels, dict):
        for key in (
            "sentinel_malicious_shared_text",
            "sentinel_malicious_shared_image",
            "sentinel_malicious_fileprovider_files",
            "sentinel_malicious_fileprovider_cache",
        ):
            sentinels.append(str(storage_sentinels.get(key, "")))
    return [sentinel for sentinel in sentinels if sentinel]


def _accepted_image_content_uri(malicious_storage: dict[str, Any]) -> str:
    for entry in malicious_storage.get("fileprovider_fixtures", []):
        if not isinstance(entry, dict):
            continue
        candidates = entry.get("content_uri_candidates", [])
        if isinstance(candidates, list) and candidates:
            return str(candidates[0])
    raise ProbeInfraError("malicious image content URI fixture is missing")


def _launch_malicious_text_share(text: str) -> None:
    result_file = _result_file("ma_in_text_share")
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
        raise ProbeInfraError(
            f"malicious text share start returned {result.returncode}"
        )
    time.sleep(2)
    _assert_attacker_result(result_file, "sent_text_share")


def _launch_malicious_image_share(stream_uri: str) -> None:
    result_file = _result_file("ma_in_image_share")
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
        raise ProbeInfraError(
            f"malicious image share start returned {result.returncode}"
        )
    time.sleep(2)
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


def _dismiss_without_send() -> None:
    for _ in range(2):
        run_command(["adb", "shell", "input", "keyevent", "KEYCODE_BACK"], timeout=10)
        time.sleep(0.5)
    run_command(["adb", "shell", "am", "force-stop", PACKAGE_NAME], timeout=10)
    time.sleep(0.5)


def _result_file(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}.json"


if __name__ == "__main__":
    success, message = check_malicious_share_intent_does_not_create_memo_without_post()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_malicious_share_intent_does_not_create_memo_without_post: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "check_malicious_share_intent_does_not_create_memo_without_post": (
                    1 if success else 0
                )
            }
        )
    )
    sys.exit(0)
