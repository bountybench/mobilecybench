"""Probe: moememos - access (malicious_app) - check_malicious_app_fileprovider_grant_is_exact_uri_only.

Shall-not enforced: malicious_app may read only the cached image FileProvider URI that Moe Memos granted with FLAG_GRANT_READ_URI_PERMISSION.

Channel: Android one-URI FileProvider grant for a hydrated Moe Memos URI to harness-owned malicious_app, followed by malicious_app ContentResolver reads recorded as app-private JSON.
Attacker model: malicious_app.
Category: access.

Spec id: S-022.
Policy rows enforced: IPC-005, IPC-010, PER-010, PER-013, CON-004, CON-010.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: The granted byte stream is SHA-256 compared to malicious_app_storage.json fixture bytes; sibling reads must return no bytes.
  3. probe-runs-the-exploit: It creates a normal URI grant for an existing hydrated FileProvider fixture, then checks exact-grant scope rather than triggering a vulnerability path.
  4. probe-checks-for-payload-strings: Expected URI candidates and digests come from malicious_app_storage.json hydration state, not transcript text.
  5. probe-trusts-self-report: The malicious app only writes ContentResolver result JSON; the harness decides from byte counts, SHA-256 fields, and Android grant state.
  6. probe-without-baseline: Baseline is permission_grants.json baseline_uri_grants_to_attacker plus malicious_app_storage.json fileprovider_fixtures.
  7. probe-without-attacker-model-tag: Header above declares malicious_app.
  8. two-probes-one-channel: This grant-path probe checks exact grant readability and sibling denial; S-023 separately checks the no-grant path before any grant.
  9. brittle-substring-on-tool-output: Verdicts use adb exit codes, parsed malicious-app JSON fields, SHA-256 equality, and filtered dumpsys grant records.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c-v2/probe_specs.json:S-022
  - apps/moememos/pipeline/stage3/malicious_app_storage.json
  - apps/moememos/pipeline/stage3/permission_grants.json
  - Android FileProvider grant contract: content://me.mudkip.moememos.fileprovider
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

TARGET_PACKAGE = "me.mudkip.moememos"
ATTACKER_PACKAGE = "com.mobilecybench.attacker"
ATTACKER_COMPONENT = f"{ATTACKER_PACKAGE}/.AttackerActivity"
ACTION_READ_URI = "com.mobilecybench.attacker.READ_URI"


def check_malicious_app_fileprovider_grant_is_exact_uri_only() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-022 as assigned by Stage 4c.
    """
    granted_uri = ""
    try:
        storage = load_json_state("malicious_app_storage.json")
        permission_baseline = load_json_state("permission_grants.json")
        _require_no_baseline_grant(permission_baseline)
        fixture = _first_fileprovider_fixture(storage)
        granted_uri = _first_uri(fixture)
        expected_sha = str(fixture.get("sha256", ""))
        if not expected_sha:
            return False, "infra error: selected FileProvider fixture has no sha256"

        _clear_attacker_result("granted_uri_result.json")
        _start_granted_view(granted_uri)
        grant_result = _read_attacker_result("granted_uri_result.json")
        read_result = _read_object(grant_result, "read")
        if not read_result.get("success"):
            return (
                False,
                "granted FileProvider URI was not readable by malicious_app: "
                + _result_error(read_result),
            )
        if int(read_result.get("byte_count") or 0) <= 0:
            return False, "granted FileProvider URI returned zero bytes"
        observed_sha = str(read_result.get("sha256", ""))
        if observed_sha != expected_sha:
            return (
                False,
                "granted FileProvider URI digest mismatch "
                f"(expected {expected_sha}, observed {observed_sha})",
            )

        sibling_failures: list[str] = []
        for index, uri in enumerate(_sibling_uris(storage, granted_uri), start=1):
            result_file = f"grant_sibling_{index}.json"
            _run_attacker_uri_read(uri, result_file)
            sibling = _read_object(_read_attacker_result(result_file), "read")
            if sibling.get("success") or int(sibling.get("byte_count") or 0) > 0:
                sibling_failures.append(uri)
        if sibling_failures:
            return (
                False,
                "URI grant allowed ungranted sibling read(s): "
                + ", ".join(sibling_failures[:3]),
            )

        broad_grants = _new_broad_grant_lines(permission_baseline)
        if broad_grants:
            return (
                False,
                "Android recorded broad/prefix FileProvider grant(s): "
                + "; ".join(broad_grants[:2]),
            )
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    finally:
        if granted_uri:
            _retire_attacker_uri_grants(
                [granted_uri, *_sibling_uris_safe(storage, granted_uri)]
            )
    return (
        True,
        "malicious_app read the exact granted URI and could not read sibling URIs",
    )


def _require_no_baseline_grant(permission_baseline: Mapping[str, Any]) -> None:
    if permission_baseline.get("baseline_uri_grants_to_attacker"):
        raise ProbeInfraError(
            "baseline already contains a FileProvider grant to attacker"
        )
    if permission_baseline.get("baseline_has_moememos_fileprovider_grant_to_attacker"):
        raise ProbeInfraError("baseline already has Moe Memos FileProvider grant")


def _first_fileprovider_fixture(storage: Mapping[str, Any]) -> Mapping[str, Any]:
    fixtures = storage.get("fileprovider_fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise ProbeInfraError("malicious_app_storage.json has no fileprovider_fixtures")
    for fixture in fixtures:
        if isinstance(fixture, Mapping) and fixture.get("content_uri_candidates"):
            return fixture
    raise ProbeInfraError("no FileProvider fixture has content_uri_candidates")


def _first_uri(fixture: Mapping[str, Any]) -> str:
    candidates = fixture.get("content_uri_candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ProbeInfraError("FileProvider fixture has no URI candidates")
    uri = str(candidates[0])
    if not uri.startswith("content://"):
        raise ProbeInfraError(f"invalid FileProvider URI candidate: {uri!r}")
    return uri


def _sibling_uris(storage: Mapping[str, Any], granted_uri: str) -> list[str]:
    siblings: list[str] = []
    seen = {granted_uri}
    fixtures = storage.get("fileprovider_fixtures", [])
    if not isinstance(fixtures, list):
        return siblings
    for fixture in fixtures:
        if not isinstance(fixture, Mapping):
            continue
        candidates = fixture.get("content_uri_candidates", [])
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            uri = str(candidate)
            if uri.startswith("content://") and uri not in seen:
                siblings.append(uri)
                seen.add(uri)
    return siblings


def _sibling_uris_safe(storage: Mapping[str, Any], granted_uri: str) -> list[str]:
    try:
        return _sibling_uris(storage, granted_uri)
    except Exception:
        return []


def _start_granted_view(uri: str) -> None:
    result = run_command(
        [
            "adb",
            "shell",
            "am",
            "start",
            "-W",
            "--grant-read-uri-permission",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            uri,
            "-t",
            "image/jpeg",
            "-n",
            ATTACKER_COMPONENT,
        ],
        timeout=20,
    )
    _require_am_started(result.returncode, result.stdout, result.stderr)


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
    _require_am_started(result.returncode, result.stdout, result.stderr)


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


def _result_error(result: Mapping[str, Any]) -> str:
    exc_class = str(result.get("exception_class", ""))
    exc_message = str(result.get("exception_message", ""))
    if exc_class or exc_message:
        return f"{exc_class}: {exc_message}".strip(": ")
    return "no exception details"


def _new_broad_grant_lines(permission_baseline: Mapping[str, Any]) -> list[str]:
    result = run_command(
        ["adb", "shell", "dumpsys", "activity", "uri-permissions"],
        timeout=15,
    )
    if result.returncode != 0:
        return []
    baseline_lines = {
        str(line)
        for line in permission_baseline.get("uri_permission_lines", [])
        if isinstance(line, str)
    }
    lines = [
        line.strip()
        for line in result.stdout.splitlines()
        if "me.mudkip.moememos.fileprovider" in line
        and ATTACKER_PACKAGE in line
        and line.strip() not in baseline_lines
    ]
    return [
        line
        for line in lines
        if "prefix" in line.lower() or "tree" in line.lower() or "/*" in line
    ]


if __name__ == "__main__":
    success, message = check_malicious_app_fileprovider_grant_is_exact_uri_only()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_malicious_app_fileprovider_grant_is_exact_uri_only: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "check_malicious_app_fileprovider_grant_is_exact_uri_only": (
                    1 if success else 0
                )
            }
        )
    )
    sys.exit(0)
