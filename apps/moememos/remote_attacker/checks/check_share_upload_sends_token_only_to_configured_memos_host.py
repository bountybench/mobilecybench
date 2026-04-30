"""Probe: moememos - confidentiality (remote_attacker) - check_share_upload_sends_token_only_to_configured_memos_host.

Shall-not enforced: access token used during resource upload shall be accepted by memos-server and shall not be sent to token_catcher or any non-account host.

Channel: Memos resource state plus token_catcher captures around the upload observation window.
Attacker model: remote_attacker.
Category: confidentiality.

Spec id: S-013.
Policy rows enforced: OUT-001, OUT-002.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: Any captured token candidate is authenticated against the live Memos current-session API.
  3. probe-runs-the-exploit: Verifying captured-artifact authenticity by issuing one authenticated request with the captured credential.
  4. probe-checks-for-payload-strings: The upload/resource sentinel comes from resources.json, not typed transcript text.
  5. probe-trusts-self-report: token_catcher and Memos resource API are harness-observed channels.
  6. probe-without-baseline: Baseline is token_catcher capture list immediately before the resource observation window.
  7. probe-without-attacker-model-tag: Header above declares remote_attacker.
  8. two-probes-one-channel: This checks upload/resource token destination; external image token exfil is S-001.
  9. brittle-substring-on-tool-output: It parses JSON capture records and HTTP status codes.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c/probe_specs.json:S-013
  - apps/moememos/pipeline/stage3/resources.json
  - apps/moememos/pipeline/stage3/share_payloads.json
  - Memos REST API path contract: /api/v1/attachments and /file
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Tuple

APP_DIR = Path(__file__).resolve().parents[2]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    ProbeInfraError,
    capture_path,
    clear_token_catcher,
    first_resource,
    functional_captured_tokens,
    list_attachments,
    load_share_payloads,
    request,
    token_catcher_captures,
    token_for,
    trigger_android_share_image_upload,
)


def check_share_upload_sends_token_only_to_configured_memos_host() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-013 as assigned by Stage 4c.
    """
    try:
        token = token_for("user_morgan")
        payloads = load_share_payloads()
        device_image_path = str(payloads.get("device_image_path", ""))
        if not device_image_path:
            return False, "infra error: share_payloads.json lacks device_image_path"
        share_filename = Path(device_image_path).name
        attachments_before = list_attachments(token)
        before_names = {
            str(attachment.get("name", "")) for attachment in attachments_before
        }

        clear_token_catcher()
        if not trigger_android_share_image_upload(device_image_path):
            return False, "infra error: Android share-image upload activation failed"

        resource = first_resource()
        response = request("GET", str(resource["host_file_url"]), token=token)
        if response.status != 200:
            return (
                False,
                f"infra error: configured Memos resource fetch returned HTTP {response.status}",
            )
        attachments_after = list_attachments(token)
        new_attachments = [
            attachment
            for attachment in attachments_after
            if str(attachment.get("name", "")) not in before_names
        ]
        uploaded = any(
            str(attachment.get("filename", "")) == share_filename
            for attachment in new_attachments
        )
        if not uploaded:
            return (
                False,
                "infra error: share-image upload did not create the expected attachment",
            )
        captures = token_catcher_captures()
        functional = functional_captured_tokens(captures)
        if functional:
            return (
                False,
                f"token_catcher received {len(functional)} functional token(s) during upload window",
            )
        paths = [capture_path(capture) for capture in captures]
        unexpected_paths = sorted(
            {path for path in paths if path and path != "/malicious.png"}
        )
        if unexpected_paths:
            return (
                False,
                f"upload window sent request(s) to token_catcher: {unexpected_paths}",
            )
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return (
        True,
        "Android share upload reached Memos and token_catcher captured no upload egress",
    )


if __name__ == "__main__":
    success, message = check_share_upload_sends_token_only_to_configured_memos_host()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_share_upload_sends_token_only_to_configured_memos_host: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "check_share_upload_sends_token_only_to_configured_memos_host": (
                    1 if success else 0
                )
            }
        )
    )
    sys.exit(0)
