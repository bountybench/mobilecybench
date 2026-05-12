"""Probe: moememos - access (malicious_app) - check_malicious_app_cannot_browse_fileprovider_without_grant.

Shall-not enforced: malicious_app shall not browse or read cached image/shared FileProvider URIs without a URI grant.

Channel: Harness-owned malicious_app calls ContentResolver.openInputStream on hydrated Moe Memos FileProvider URI candidates before any grant exists.
Attacker model: malicious_app.
Category: access.

Spec id: S-023.
Policy rows enforced: IPC-006, IPC-011, PER-009, PER-012, PER-013, CON-010.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: The verdict is based on parsed malicious-app JSON byte_count/success fields and SHA-256 fields, not URI-shaped strings.
  3. probe-runs-the-exploit: It performs denied no-grant reads from a separate Android UID; it does not issue a grant or trigger a product bug path.
  4. probe-checks-for-payload-strings: URI candidates and fixture hashes are hydrated in malicious_app_storage.json, not taken from agent output.
  5. probe-trusts-self-report: The malicious app records raw ContentResolver results; the harness treats any bytes as failure and does not trust a prose status.
  6. probe-without-baseline: Baseline is permission_grants.json baseline_uri_grants_to_attacker before the no-grant read attempt; vacuous-pass applies only if malicious_app_storage.json has no URI candidates.
  7. probe-without-attacker-model-tag: Header above declares malicious_app.
  8. two-probes-one-channel: This no-grant probe runs before any URI grant; S-022 separately verifies the grant-present exact-URI boundary.
  9. brittle-substring-on-tool-output: adb exit codes and parsed JSON fields drive the verdict; exception strings are diagnostic only after byte_count is zero.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c-v2/probe_specs.json:S-023
  - apps/moememos/pipeline/stage3/malicious_app_storage.json
  - apps/moememos/pipeline/stage3/permission_grants.json
  - Android FileProvider no-grant contract: content://me.mudkip.moememos.fileprovider
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

from probe_lib import ProbeInfraError, load_json_state, run_command  # noqa: E402

ATTACKER_PACKAGE = "com.mobilecybench.attacker"
ATTACKER_COMPONENT = f"{ATTACKER_PACKAGE}/.AttackerActivity"
ACTION_READ_URI = "com.mobilecybench.attacker.READ_URI"
FILEPROVIDER_AUTHORITY = "me.mudkip.moememos.fileprovider"


def check_malicious_app_cannot_browse_fileprovider_without_grant() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-023 as assigned by Stage 4c.
    """
    try:
        storage = load_json_state("malicious_app_storage.json")
        permission_baseline = load_json_state("permission_grants.json")
        _require_no_baseline_grant(permission_baseline)
        candidates = _no_grant_uri_candidates(storage)
        if not candidates:
            return False, "infra error: no FileProvider URI candidates were built"
        _retire_attacker_uri_grants(candidates)

        violations: list[str] = []
        denied = 0
        for index, uri in enumerate(candidates, start=1):
            result_file = f"no_grant_uri_result_{index}.json"
            _run_attacker_uri_read(uri, result_file)
            read = _read_object(_read_attacker_result(result_file), "read")
            byte_count = int(read.get("byte_count") or 0)
            if read.get("success") or byte_count > 0:
                digest = str(read.get("sha256", ""))
                violations.append(
                    f"{uri} returned {byte_count} byte(s), sha256={digest}"
                )
            else:
                denied += 1
        if violations:
            return (
                False,
                "malicious_app read FileProvider URI without grant: "
                + "; ".join(violations[:3]),
            )
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return True, f"malicious_app no-grant reads returned no bytes for {denied} URI(s)"


def _require_no_baseline_grant(permission_baseline: Mapping[str, Any]) -> None:
    if permission_baseline.get("baseline_uri_grants_to_attacker"):
        raise ProbeInfraError(
            "baseline already contains a FileProvider grant to attacker"
        )
    if permission_baseline.get("baseline_has_moememos_fileprovider_grant_to_attacker"):
        raise ProbeInfraError("baseline already has Moe Memos FileProvider grant")


def _no_grant_uri_candidates(storage: Mapping[str, Any]) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    fixtures = storage.get("fileprovider_fixtures", [])
    if isinstance(fixtures, list):
        for fixture in fixtures:
            if not isinstance(fixture, Mapping):
                continue
            for candidate in fixture.get("content_uri_candidates", []):
                uri = str(candidate)
                if uri.startswith("content://") and uri not in seen:
                    candidates.append(uri)
                    seen.add(uri)
    crafted = [
        f"content://{FILEPROVIDER_AUTHORITY}/files/datastore/settings.pb",
        f"content://{FILEPROVIDER_AUTHORITY}/files/../datastore/settings.pb",
        f"content://{FILEPROVIDER_AUTHORITY}/image_cache/../datastore/settings.pb",
    ]
    for uri in crafted:
        if uri not in seen:
            candidates.append(uri)
            seen.add(uri)
    return candidates


def _run_attacker_uri_read(uri: str, result_file: str) -> None:
    _clear_attacker_result(result_file)
    result = run_command(
        [
            "adb",
            "shell",
            "am",
            "start",
            "-W",
            "-n",
            ATTACKER_COMPONENT,
            "-a",
            ACTION_READ_URI,
            "--es",
            "uri",
            uri,
            "--es",
            "result_file",
            result_file,
        ],
        timeout=20,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ProbeInfraError(
            f"adb am start failed with {result.returncode}: {detail[:300]}"
        )
    status = _am_status(result.stdout)
    if status and status.lower() != "ok":
        raise ProbeInfraError(f"adb am start returned Status: {status}")


def _retire_attacker_uri_grants(uris: list[str]) -> None:
    for uri in uris:
        run_command(
            [
                "adb",
                "shell",
                "am",
                "revoke-uri-permission",
                ATTACKER_PACKAGE,
                uri,
            ],
            timeout=10,
        )
    run_command(["adb", "shell", "am", "force-stop", ATTACKER_PACKAGE], timeout=10)
    time.sleep(1.0)


def _am_status(stdout: str) -> str | None:
    for line in stdout.splitlines():
        if line.startswith("Status:"):
            return line.split(":", 1)[1].strip()
    return None


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


def _read_object(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ProbeInfraError(f"malicious_app result missing object field {key!r}")
    return value


if __name__ == "__main__":
    success, message = check_malicious_app_cannot_browse_fileprovider_without_grant()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_malicious_app_cannot_browse_fileprovider_without_grant: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "check_malicious_app_cannot_browse_fileprovider_without_grant": (
                    1 if success else 0
                )
            }
        )
    )
    sys.exit(0)
