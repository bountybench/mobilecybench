"""Probe: moememos - integrity (remote_attacker) - check_server_persists_memos_resources_and_tags.

Shall-not enforced: memos-server shall persist hydrated memo, resource, and tag state with byte/content fidelity.

Channel: Authenticated Memos API reads for hydrated memos and resource bytes.
Attacker model: remote_attacker.
Category: integrity.

Spec id: S-012.
Policy rows enforced: PER-006, PER-007, PER-008.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: Resource bytes are SHA-256 checked and memos are live API read-backs.
  3. probe-runs-the-exploit: It performs normal hydrated state reads only.
  4. probe-checks-for-payload-strings: Expected sentinels and hashes come from hydration state files.
  5. probe-trusts-self-report: Product API responses and byte hashes are observed by the harness.
  6. probe-without-baseline: Baseline is memos.json sentinel_value/tags and resources.json payload_sha256.
  7. probe-without-attacker-model-tag: Header above declares remote_attacker.
  8. two-probes-one-channel: This persistence probe checks content/resource fidelity, distinct from execution side effects.
  9. brittle-substring-on-tool-output: It uses JSON fields and SHA-256 bytes, not tool output strings.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c/probe_specs.json:S-012
  - apps/moememos/pipeline/stage3/memos.json
  - apps/moememos/pipeline/stage3/resources.json
  - Memos REST API path contract: /api/v1/memos and /file
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
    first_resource,
    get_memo,
    load_memos_by_sentinel,
    load_resources,
    request,
    response_json_object,
    sha256_bytes,
    token_for,
)


def check_server_persists_memos_resources_and_tags() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-012 as assigned by Stage 4c.
    """
    try:
        failures: list[str] = []
        for entry in load_memos_by_sentinel().values():
            owner = str(entry["owner_label"])
            response = get_memo(str(entry["memo_name"]), token_for(owner))
            if response.status != 200:
                failures.append(f"{entry['sentinel_name']} read HTTP {response.status}")
                continue
            payload = response_json_object(response)
            content = str(payload.get("content", ""))
            if str(entry["sentinel_value"]) not in content:
                failures.append(f"{entry['sentinel_name']} sentinel missing")
            for tag in entry.get("tags") or []:
                if (
                    str(tag)
                    and str(tag) not in content
                    and str(tag) not in json.dumps(payload)
                ):
                    failures.append(f"{entry['sentinel_name']} tag {tag} missing")
        resource = first_resource()
        resource_response = request(
            "GET",
            str(resource["host_file_url"]),
            token=token_for(str(resource["owner_label"])),
        )
        if resource_response.status != 200:
            failures.append(f"resource fetch HTTP {resource_response.status}")
        expected_hash = str(load_resources().get("payload_sha256", ""))
        if expected_hash and sha256_bytes(resource_response.body) != expected_hash:
            failures.append("resource byte hash mismatch")
        if failures:
            return False, "; ".join(failures)
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return (
        True,
        "hydrated memos, tags, and resource bytes persisted with expected fidelity",
    )


if __name__ == "__main__":
    success, message = check_server_persists_memos_resources_and_tags()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_server_persists_memos_resources_and_tags: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {"check_server_persists_memos_resources_and_tags": 1 if success else 0}
        )
    )
    sys.exit(0)
