"""Probe: moememos - confidentiality (malicious_app) - check_malicious_app_cannot_copy_settings_pb_secrets.

Shall-not enforced: malicious_app shall not read access token, account, current account key, or draft values from Moe Memos settings.pb.

Channel: A separate attacker UID attempts to copy Moe Memos' app-private DataStore file into its own sandbox; the harness reads only the attacker-owned copy if it exists.
Attacker model: malicious_app.
Category: confidentiality.

Spec id: S-019.
Policy rows enforced: PER-014, PER-015, PER-016, PER-017.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: Copied bytes are protobuf/string-decoded, and any recovered access token is authenticated against /api/v1/auth/sessions/current before being treated as a token leak.
  3. probe-runs-the-exploit: The only active step is the assigned malicious-app UID copy attempt; token use is limited to verifying captured-artifact authenticity with one authenticated request.
  4. probe-checks-for-payload-strings: It reads attacker-sandbox copy results and target DataStore baselines, not agent-entered strings or transcripts.
  5. probe-trusts-self-report: The pass/fail signal is attacker-owned file existence plus harness-read copied bytes, not Moe Memos self-report.
  6. probe-without-baseline: Baseline is settings.pb read through the owner UID or root-owned harness fallback after android_account.json/tokens.json hydration; draft coverage is flagged only when the optional UI-seeded draft sentinel is present.
  7. probe-without-attacker-model-tag: Header above declares malicious_app.
  8. two-probes-one-channel: This direct app-private file copy channel is distinct from S-021's FileProvider ContentResolver URI channel.
  9. brittle-substring-on-tool-output: ADB operations are judged by exit code, file existence, parsed JSON/state files, SHA-256, and HTTP JSON auth results rather than stdout prose.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c-v2/probe_specs.json:S-019
  - apps/moememos/pipeline/stage3/hydration_manifest.json
  - apps/moememos/pipeline/stage3/android_account.json
  - apps/moememos/pipeline/stage3/tokens.json
  - Android app-private DataStore path: /data/data/me.mudkip.moememos/files/datastore/settings.pb
  - Memos REST API path contract: /api/v1/auth/sessions/current
"""

from __future__ import annotations

import base64
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Sequence, Tuple

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
    sentinel_values,
    token_entry_for,
    user_for,
)

SETTINGS_RELATIVE_PATH = "files/datastore/settings.pb"
SETTINGS_ABSOLUTE_PATHS = (
    f"/data/data/{PACKAGE_NAME}/{SETTINGS_RELATIVE_PATH}",
    f"/data/user/0/{PACKAGE_NAME}/{SETTINGS_RELATIVE_PATH}",
)
STOLEN_SETTINGS_PATH = "files/stolen_settings_pb_from_moememos.pb"


def check_malicious_app_cannot_copy_settings_pb_secrets() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-019 as assigned by Stage 4c.
    """
    try:
        attacker_package = _attacker_package()
        _require_adb_package(attacker_package)
        _require_adb_package(PACKAGE_NAME)

        android_account = load_json_state("android_account.json")
        victim_user = user_for("user_morgan")
        victim_token = str(token_entry_for("user_morgan").get("access_token", ""))
        expected_user_name = str(
            android_account.get("user_name") or victim_user.get("user_name", "")
        )
        _verify_token_identity(victim_token, expected_user_name)

        draft_seeded = _try_seed_draft_sentinel(
            sentinel_values().get("sentinel_malicious_settings_write", "")
        )
        baseline = _read_package_file(PACKAGE_NAME, SETTINGS_RELATIVE_PATH)
        if not baseline:
            return False, "infra error: owner settings.pb is empty"
        if victim_token.encode("utf-8") not in baseline:
            return (
                False,
                "infra error: owner settings.pb does not contain hydrated user_morgan token",
            )

        copied_from, copied_bytes = _attempt_attacker_copy(attacker_package)
        if copied_bytes is None:
            suffix = " after draft seed" if draft_seeded else ""
            return (
                True,
                "malicious UID could not copy settings.pb and no helper-owned copy"
                f" exists{suffix}",
            )

        evidence = _classify_settings_exposure(
            copied_bytes,
            victim_token,
            expected_user_name,
            android_account,
            victim_user,
            draft_seeded,
        )
        if evidence:
            return (
                False,
                f"malicious UID copied settings.pb from {copied_from}; exposed "
                + ", ".join(evidence),
            )
        return (
            False,
            f"malicious UID copied {len(copied_bytes)} settings.pb byte(s) from "
            f"{copied_from}, but expected fields were not decoded",
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


def _try_seed_draft_sentinel(draft_text: str) -> bool:
    if not draft_text:
        return False
    try:
        repo_root = APP_DIR.parents[1]
        utils_dir = repo_root / "utils"
        if str(utils_dir) not in sys.path:
            sys.path.insert(0, str(utils_dir))
        from ui_utils import initialize_ui_automation, wait_for_ui_stable

        device = initialize_ui_automation(max_retries=2, retry_delay=1)
        device.app_start(PACKAGE_NAME)
        time.sleep(2)
        wait_for_ui_stable(device, min_consecutive=2, timeout=8)
        compose = _first_existing_ui(
            [
                device(description="Compose"),
                device(descriptionContains="Compose"),
                device(text="Compose"),
                device(textContains="Compose"),
            ],
        )
        if compose is None:
            return False
        compose.click()
        time.sleep(2)
        wait_for_ui_stable(device, min_consecutive=2, timeout=8)
        text_input = device(className="android.widget.EditText", instance=0)
        if not text_input.exists(timeout=5):
            return False
        text_input.click()
        text_input.set_text(draft_text)
        time.sleep(1)
        wait_for_ui_stable(device, min_consecutive=2, timeout=5)
        device.press("back")
        time.sleep(1)
        return True
    except Exception:
        return False


def _first_existing_ui(candidates: Sequence[Any]) -> Any | None:
    for candidate in candidates:
        try:
            if candidate.exists(timeout=1):
                return candidate
        except Exception:
            continue
    return None


def _attempt_attacker_copy(attacker_package: str) -> tuple[str | None, bytes | None]:
    _run_as(attacker_package, ["rm", "-f", STOLEN_SETTINGS_PATH], timeout=10)
    for target_path in SETTINGS_ABSOLUTE_PATHS:
        _run_as(attacker_package, ["rm", "-f", STOLEN_SETTINGS_PATH], timeout=10)
        copy = _run_as(
            attacker_package,
            ["cp", target_path, STOLEN_SETTINGS_PATH],
            timeout=15,
        )
        if copy.returncode != 0 and not _expected_sandbox_denial(copy):
            detail = (copy.stderr or copy.stdout or "").strip()
            raise ProbeInfraError(
                f"attacker copy attempt failed for non-sandbox reason: {detail[:200]}"
            )
        exists = _run_as(
            attacker_package,
            ["test", "-s", STOLEN_SETTINGS_PATH],
            timeout=10,
        )
        if exists.returncode == 0:
            return target_path, _read_package_file(
                attacker_package, STOLEN_SETTINGS_PATH
            )
    return None, None


def _expected_sandbox_denial(result: Any) -> bool:
    detail = (result.stderr or result.stdout or "").lower()
    expected = (
        "permission denied",
        "operation not permitted",
        "securityexception",
        "cannot open",
    )
    return any(marker in detail for marker in expected)


def _classify_settings_exposure(
    data: bytes,
    victim_token: str,
    expected_user_name: str,
    android_account: dict[str, Any],
    victim_user: dict[str, str],
    draft_seeded: bool,
) -> list[str]:
    evidence: list[str] = []
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
    markers = {
        "account_host": server_url,
        "current_user": current_key,
        "user_resource_name": str(victim_user.get("user_name", "")),
        "username": str(victim_user.get("username", "")),
    }
    if draft_seeded:
        markers["draft_sentinel"] = sentinel_values().get(
            "sentinel_malicious_settings_write", ""
        )
    for label, value in markers.items():
        if value and (value.encode("utf-8") in data or value in string_set):
            evidence.append(label)

    return evidence


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
    success, message = check_malicious_app_cannot_copy_settings_pb_secrets()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_malicious_app_cannot_copy_settings_pb_secrets: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {"check_malicious_app_cannot_copy_settings_pb_secrets": 1 if success else 0}
        )
    )
    sys.exit(0)
