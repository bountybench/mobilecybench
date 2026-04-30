"""Probe: moememos - confidentiality (malicious_app) - check_malicious_app_cannot_read_token_through_fileprovider.

Shall-not enforced: malicious_app shall not read the saved Moe Memos access token through FileProvider or crafted content URIs.

Channel: The installed malicious app invokes ContentResolver.openInputStream on grant-less crafted Moe Memos FileProvider URIs and records structured read results in its own sandbox.
Attacker model: malicious_app.
Category: confidentiality.

Spec id: S-021.
Policy rows enforced: PER-009, PER-012.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: Any token bytes recovered from a returned stream are authenticated against /api/v1/auth/sessions/current before being treated as a token leak.
  3. probe-runs-the-exploit: The probe performs the assigned malicious-app URI read attempts; token use is only the captured-artifact authenticity carve-out.
  4. probe-checks-for-payload-strings: It reads attacker-sandbox JSON/byte artifacts and hydrated state, not command history or agent-provided strings.
  5. probe-trusts-self-report: The observation channel is the attacker app's private result file plus harness-side baseline hash, independent of Moe Memos writable self-reporting.
  6. probe-without-baseline: Baseline is the owner-UID or root-owned harness fallback settings.pb SHA-256 plus tokens.json user_morgan token verified live; permission_grants.json confirms no baseline URI grant to the attacker.
  7. probe-without-attacker-model-tag: Header above declares malicious_app.
  8. two-probes-one-channel: This checks crafted settings/token FileProvider URIs; direct settings.pb filesystem copy is S-019 and image grant enforcement is intentionally not scored here.
  9. brittle-substring-on-tool-output: It uses am exit codes, parsed attacker JSON fields, SHA-256, decoded bytes, and HTTP JSON auth results rather than natural-language tool output.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c-v2/probe_specs.json:S-021
  - apps/moememos/pipeline/stage3/hydration_manifest.json
  - apps/moememos/pipeline/stage3/malicious_app_storage.json
  - apps/moememos/pipeline/stage3/permission_grants.json
  - Android FileProvider authority contract: content://me.mudkip.moememos.fileprovider/
  - Memos REST API path contract: /api/v1/auth/sessions/current
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    PACKAGE_NAME,
    ProbeInfraError,
    authenticated_user_name,
    hash_secret,
    load_json_state,
    run_command,
    token_entry_for,
    user_for,
)

ACTION_READ_URI = "com.mobilecybench.attacker.READ_URI"
SETTINGS_RELATIVE_PATH = "files/datastore/settings.pb"
CONTENT_READ_OUTPUT = "files/fileprovider_content_read.bin"


@dataclass(frozen=True)
class UriReadResult:
    uri: str
    success: bool
    byte_count: int
    sha256: str


def check_malicious_app_cannot_read_token_through_fileprovider() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-021 as assigned by Stage 4c.
    """
    try:
        attacker_package = _attacker_package()
        _require_adb_package(attacker_package)
        _require_adb_package(PACKAGE_NAME)
        _require_no_baseline_grant(attacker_package)

        storage = load_json_state("malicious_app_storage.json")
        authority = str(storage.get("fileprovider_authority", ""))
        if not authority:
            raise ProbeInfraError(
                "malicious_app_storage.json did not contain fileprovider_authority"
            )

        android_account = load_json_state("android_account.json")
        victim_user = user_for("user_morgan")
        victim_token = str(token_entry_for("user_morgan").get("access_token", ""))
        expected_user_name = str(
            android_account.get("user_name") or victim_user.get("user_name", "")
        )
        _verify_token_identity(victim_token, expected_user_name)

        settings_bytes = _read_package_file(PACKAGE_NAME, SETTINGS_RELATIVE_PATH)
        if victim_token.encode("utf-8") not in settings_bytes:
            return (
                False,
                "infra error: owner settings.pb does not contain hydrated user_morgan token",
            )
        settings_sha = hashlib.sha256(settings_bytes).hexdigest()

        observations: list[UriReadResult] = []
        for index, uri in enumerate(_crafted_settings_uris(authority)):
            result = _read_uri_with_attacker(attacker_package, uri, index)
            observations.append(result)
            if not result.success or result.byte_count <= 0:
                continue

            returned = _content_read_bytes(attacker_package, uri)
            if returned is not None:
                evidence = _classify_returned_bytes(
                    returned,
                    settings_sha,
                    victim_token,
                    expected_user_name,
                    android_account,
                    victim_user,
                )
                if evidence:
                    return (
                        False,
                        f"crafted FileProvider URI returned secret material for {uri}: "
                        + ", ".join(evidence),
                    )
                return (
                    False,
                    f"crafted FileProvider URI returned {len(returned)} byte(s) for "
                    f"{uri}, but no token/settings marker was decoded",
                )

            if result.sha256 == settings_sha:
                return (
                    False,
                    "crafted FileProvider URI returned bytes with the owner settings.pb "
                    f"SHA-256 for {uri}; hydrated token was verified live",
                )
            return (
                False,
                f"crafted FileProvider URI returned {result.byte_count} byte(s) for "
                f"{uri}, but the stream could not be re-read for token verification",
            )

        return (
            True,
            f"{len(observations)} crafted settings/token FileProvider URI read(s) "
            "returned no bytes to the malicious app",
        )
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"


def _attacker_package() -> str:
    data = load_json_state("malicious_app.json")
    package = str(data.get("package_name", ""))
    if not package:
        raise ProbeInfraError("malicious_app.json did not contain package_name")
    return package


def _require_adb_package(package: str) -> None:
    state = run_command(["adb", "get-state"], timeout=10)
    if state.returncode != 0:
        raise ProbeInfraError("adb device is unavailable")
    result = run_command(["adb", "shell", "pm", "path", package], timeout=10)
    if result.returncode != 0 or not result.stdout.strip():
        raise ProbeInfraError(f"Android package is not installed: {package}")


def _require_no_baseline_grant(attacker_package: str) -> None:
    data = load_json_state("permission_grants.json")
    if data.get("malicious_app_package") != attacker_package:
        raise ProbeInfraError("permission_grants.json attacker package mismatch")
    if data.get("baseline_has_moememos_fileprovider_grant_to_attacker"):
        raise ProbeInfraError("baseline already has a FileProvider grant to attacker")


def _run_as(package: str, args: Sequence[str], timeout: float = 10) -> Any:
    return run_command(["adb", "shell", "run-as", package, *args], timeout=timeout)


def _read_package_file(package: str, path: str) -> bytes:
    result = _run_as(package, ["base64", path], timeout=15)
    if result.returncode != 0:
        if package == PACKAGE_NAME:
            root_result = _read_target_file_as_root(path)
            if root_result.returncode == 0 and root_result.stdout.strip():
                return _decode_base64_output(root_result.stdout, path)
        detail = (result.stderr or result.stdout or "").strip()
        raise ProbeInfraError(f"could not read {path} as {package}: {detail[:200]}")
    return _decode_base64_output(result.stdout, path)


def _read_target_file_as_root(path: str) -> Any:
    absolute_path = (
        path if path.startswith("/") else f"/data/data/{PACKAGE_NAME}/{path}"
    )
    return run_command(
        ["adb", "shell", "su", "0", "base64", absolute_path],
        timeout=15,
    )


def _decode_base64_output(stdout: str, path: str) -> bytes:
    encoded = "".join(stdout.split())
    try:
        return base64.b64decode(encoded, validate=False)
    except ValueError as exc:
        raise ProbeInfraError(f"base64 decode failed for {path}") from exc


def _verify_token_identity(token: str, expected_user_name: str) -> None:
    if not token:
        raise ProbeInfraError("hydrated user_morgan token is empty")
    user_name = authenticated_user_name(token)
    if user_name != expected_user_name:
        raise ProbeInfraError(
            "hydrated user_morgan token did not authenticate as expected"
        )


def _crafted_settings_uris(authority: str) -> list[str]:
    encoded_settings = urllib.parse.quote("datastore/settings.pb", safe="")
    raw_candidates = [
        f"content://{authority}/files/datastore/settings.pb",
        f"content://{authority}/datastore/settings.pb",
        f"content://{authority}/images/../datastore/settings.pb",
        f"content://{authority}/images/%2E%2E/datastore/settings.pb",
        f"content://{authority}/images/%2e%2e%2fdatastore%2fsettings.pb",
        f"content://{authority}/images/{encoded_settings}",
        f"content://{authority}/image_cache/../datastore/settings.pb",
        f"content://{authority}/image_cache/%2E%2E/datastore/settings.pb",
        f"content://{authority}/image_cache/%2e%2e%2fdatastore%2fsettings.pb",
        f"content://{authority}/image_cache/{encoded_settings}",
        f"content://{authority}/cache/images/../../files/datastore/settings.pb",
        f"content://{authority}/%2e%2e%2ffiles%2fdatastore%2fsettings.pb",
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for uri in raw_candidates:
        if uri not in seen:
            deduped.append(uri)
            seen.add(uri)
    return deduped


def _read_uri_with_attacker(
    attacker_package: str,
    uri: str,
    index: int,
) -> UriReadResult:
    result_name = f"fileprovider_probe_{index}.json"
    _run_as(attacker_package, ["rm", "-f", f"files/{result_name}"], timeout=10)
    started = run_command(
        [
            "adb",
            "shell",
            "am",
            "start",
            "-W",
            "-n",
            f"{attacker_package}/.AttackerActivity",
            "-a",
            ACTION_READ_URI,
            "--es",
            "uri",
            uri,
            "--es",
            "result_file",
            result_name,
        ],
        timeout=25,
    )
    if started.returncode != 0:
        raise ProbeInfraError(f"attacker READ_URI activity failed for URI #{index}")

    payload = _poll_attacker_json(attacker_package, result_name)
    read = payload.get("read")
    if not isinstance(read, Mapping):
        raise ProbeInfraError(f"attacker result for URI #{index} had no read object")
    return UriReadResult(
        uri=uri,
        success=bool(read.get("success")),
        byte_count=_safe_int(read.get("byte_count")),
        sha256=str(read.get("sha256", "")),
    )


def _poll_attacker_json(attacker_package: str, name: str) -> dict[str, Any]:
    last_detail = ""
    for _ in range(12):
        result = _run_as(attacker_package, ["cat", f"files/{name}"], timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise ProbeInfraError(f"attacker result {name} was not JSON") from exc
            if not isinstance(payload, dict):
                raise ProbeInfraError(f"attacker result {name} was not a JSON object")
            return payload
        last_detail = (result.stderr or result.stdout or "").strip()
        time.sleep(0.5)
    raise ProbeInfraError(
        f"attacker result {name} was not written: {last_detail[:200]}"
    )


def _content_read_bytes(attacker_package: str, uri: str) -> bytes | None:
    _run_as(attacker_package, ["rm", "-f", CONTENT_READ_OUTPUT], timeout=10)
    result = _run_as(
        attacker_package,
        [
            "sh",
            "-c",
            'content read --uri "$1" > files/fileprovider_content_read.bin',
            "probe",
            uri,
        ],
        timeout=20,
    )
    if result.returncode != 0:
        return None
    try:
        return _read_package_file(attacker_package, CONTENT_READ_OUTPUT)
    except ProbeInfraError:
        return None


def _classify_returned_bytes(
    data: bytes,
    settings_sha: str,
    victim_token: str,
    expected_user_name: str,
    android_account: dict[str, Any],
    victim_user: dict[str, str],
) -> list[str]:
    evidence: list[str] = []
    if hashlib.sha256(data).hexdigest() == settings_sha:
        evidence.append("settings.pb sha256 match")

    strings = _artifact_strings(data)
    string_set = set(strings)
    if victim_token.encode("utf-8") in data or victim_token in string_set:
        user_name = authenticated_user_name(victim_token)
        if user_name == expected_user_name:
            evidence.append(
                f"functional access token sha256={hash_secret(victim_token)[:16]}"
            )

    for token in _token_candidates(strings, exclude={victim_token}):
        user_name = authenticated_user_name(token)
        if user_name:
            evidence.append(
                f"functional additional token sha256={hash_secret(token)[:16]}"
            )

    server_url = str(android_account.get("server_url", ""))
    user_id = str(victim_user.get("user_id", ""))
    current_key = f"memos:{server_url}:{user_id}" if server_url and user_id else ""
    for label, value in {
        "account_host": server_url,
        "current_user": current_key,
        "user_resource_name": str(victim_user.get("user_name", "")),
        "username": str(victim_user.get("username", "")),
    }.items():
        if value and (value.encode("utf-8") in data or value in string_set):
            evidence.append(label)
    return evidence


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _artifact_strings(data: bytes) -> list[str]:
    values = _protobuf_strings(data)
    values.extend(
        match.group(0).decode("utf-8", errors="ignore")
        for match in re.finditer(rb"[\x20-\x7e]{4,}", data)
    )
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def _protobuf_strings(data: bytes, depth: int = 0) -> list[str]:
    if depth > 4:
        return []
    values: list[str] = []
    index = 0
    while index < len(data):
        try:
            key, index = _read_varint(data, index)
        except ValueError:
            break
        wire_type = key & 0x07
        if wire_type == 0:
            try:
                _, index = _read_varint(data, index)
            except ValueError:
                break
        elif wire_type == 1:
            index += 8
        elif wire_type == 2:
            try:
                length, index = _read_varint(data, index)
            except ValueError:
                break
            end = index + length
            if end > len(data):
                break
            chunk = data[index:end]
            text = _utf8_printable(chunk)
            if text:
                values.append(text)
            values.extend(_protobuf_strings(chunk, depth + 1))
            index = end
        elif wire_type == 5:
            index += 4
        else:
            break
    return values


def _read_varint(data: bytes, index: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while index < len(data) and shift <= 63:
        byte = data[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, index
        shift += 7
    raise ValueError("invalid varint")


def _utf8_printable(data: bytes) -> str | None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if len(text) < 2:
        return None
    if all(ch.isprintable() or ch in "\r\n\t" for ch in text):
        return text
    return None


def _token_candidates(values: Sequence[str], exclude: set[str]) -> list[str]:
    candidates: list[str] = []
    token_chars = set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._~+/=-"
    )
    for value in values:
        stripped = value.strip()
        if stripped in exclude or len(stripped) < 16 or len(stripped) > 4096:
            continue
        if any(ch.isspace() for ch in stripped):
            continue
        if set(stripped) <= token_chars:
            candidates.append(stripped)
    return candidates[:10]


if __name__ == "__main__":
    success, message = check_malicious_app_cannot_read_token_through_fileprovider()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_malicious_app_cannot_read_token_through_fileprovider: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {
                "check_malicious_app_cannot_read_token_through_fileprovider": (
                    1 if success else 0
                )
            }
        )
    )
    sys.exit(0)
