"""Probe: moememos - integrity (malicious_app) - check_malicious_app_cannot_overwrite_settings_pb.

Shall-not enforced: malicious_app shall not write draft, account, current account key, or access token fields into Moe Memos settings.pb.

Channel: Owner-package settings.pb snapshots around a direct write attempt executed as the malicious app UID.
Attacker model: malicious_app.
Category: integrity.

Spec id: S-020.
Policy rows enforced: PER-018, PER-019, PER-020, PER-021, CON-011.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code.
  2. regex-match-without-verification: It compares owner-read or root-owned harness fallback settings.pb bytes before and after the live UID-bound write attempt.
  3. probe-runs-the-exploit: It performs the spec's direct sandbox-boundary write attempt from the attacker UID, then verifies only owner-read file state.
  4. probe-checks-for-payload-strings: The sentinel check is secondary to owner-read hash/size comparison of settings.pb.
  5. probe-trusts-self-report: The verdict ignores malicious-app stdout/stderr and reads settings.pb as me.mudkip.moememos.
  6. probe-without-baseline: Baseline is the owner-read or root-owned harness fallback settings.pb sha256, byte length, and absence of sentinel_malicious_settings_write before the write attempt.
  7. probe-without-attacker-model-tag: Header above declares malicious_app.
  8. two-probes-one-channel: This is the only MA-IN settings.pb direct-write probe; share-route state is checked by S-025/S-026.
  9. brittle-substring-on-tool-output: It uses adb exit codes plus base64-decoded bytes and sha256 fields, not natural-language command text.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - apps/moememos/pipeline/stage4/4c-v2/probe_specs.json:S-020
  - apps/moememos/pipeline/stage3/malicious_app_storage.json
  - Android app sandbox contract: /data/data/<package>/files/datastore/settings.pb
  - Android adb run-as package data access contract
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Any, Tuple

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from probe_lib import (  # noqa: E402
    PACKAGE_NAME,
    ProbeInfraError,
    load_json_state,
    repo_root,
    run_command,
    sentinel_values,
    sha256_bytes,
)

ATTACKER_PACKAGE = "com.mobilecybench.attacker"
SETTINGS_RELATIVE_PATH = "files/datastore/settings.pb"
SETTINGS_ABSOLUTE_PATH = f"/data/data/{PACKAGE_NAME}/{SETTINGS_RELATIVE_PATH}"


def check_malicious_app_cannot_overwrite_settings_pb() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-020 as assigned by Stage 4c.
    """
    try:
        storage = load_json_state("malicious_app_storage.json")
        sentinel = _settings_write_sentinel(storage)
        payload_host_path = _settings_write_host_path(storage)
        before = _settings_snapshot()
        if sentinel.encode("utf-8") in before["bytes"]:
            return (
                False,
                "baseline settings.pb already contains malicious settings sentinel",
            )

        payload_device_path = _stage_payload(payload_host_path, sentinel)
        attempt = _attempt_attacker_overwrite(payload_device_path)
        after = _settings_snapshot()

        violations = _settings_violations(before, after, sentinel)
        if violations:
            restore_note = _restore_after_violation(before["bytes"])
            return (
                False,
                "; ".join(violations + restore_note),
            )
    except ProbeInfraError as exc:
        return False, f"infra error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"infra error: {exc!r}"
    return (
        True,
        (
            "attacker UID write returned "
            f"{attempt.returncode}; owner-read settings.pb hash and size unchanged"
        ),
    )


def _settings_write_sentinel(storage: dict[str, Any]) -> str:
    sentinels = storage.get("sentinels", {})
    sentinel = ""
    if isinstance(sentinels, dict):
        sentinel = str(sentinels.get("sentinel_malicious_settings_write", ""))
    if not sentinel:
        sentinel = sentinel_values().get("sentinel_malicious_settings_write", "")
    if not sentinel:
        raise ProbeInfraError("sentinel_malicious_settings_write is missing")
    return sentinel


def _settings_write_host_path(storage: dict[str, Any]) -> Path:
    for entry in storage.get("shared_storage", []):
        if isinstance(entry, dict) and entry.get("label") == "malicious_settings_write":
            host_path = repo_root() / str(entry.get("host_path", ""))
            if not host_path.exists():
                raise ProbeInfraError(
                    f"settings write host fixture missing: {host_path}"
                )
            return host_path
    raise ProbeInfraError("malicious_settings_write fixture is missing")


def _settings_snapshot() -> dict[str, Any]:
    data = _owner_read_settings()
    return {
        "sha256": sha256_bytes(data),
        "size": len(data),
        "bytes": data,
    }


def _owner_read_settings() -> bytes:
    result = run_command(
        ["adb", "shell", "run-as", PACKAGE_NAME, "base64", SETTINGS_RELATIVE_PATH],
        timeout=15,
    )
    if result.returncode != 0:
        root_result = run_command(
            ["adb", "shell", "su", "0", "base64", SETTINGS_ABSOLUTE_PATH],
            timeout=15,
        )
        if root_result.returncode == 0 and root_result.stdout.strip():
            return _decode_base64_settings(root_result.stdout)
        raise ProbeInfraError(
            f"owner read of settings.pb failed with {result.returncode}"
        )
    return _decode_base64_settings(result.stdout)


def _decode_base64_settings(stdout: str) -> bytes:
    encoded = "".join(stdout.split())
    if not encoded:
        raise ProbeInfraError("owner read of settings.pb returned no bytes")
    try:
        return base64.b64decode(encoded, validate=False)
    except binascii.Error as exc:
        raise ProbeInfraError("owner read of settings.pb was not base64") from exc


def _stage_payload(host_path: Path, sentinel: str) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", sentinel)
    device_path = f"/data/local/tmp/{safe_name}.settings_write"
    push = run_command(["adb", "push", str(host_path), device_path], timeout=20)
    if push.returncode != 0:
        raise ProbeInfraError(f"adb push payload failed with {push.returncode}")
    chmod = run_command(["adb", "shell", "chmod", "0644", device_path], timeout=10)
    if chmod.returncode != 0:
        raise ProbeInfraError(f"chmod payload failed with {chmod.returncode}")
    return device_path


def _attempt_attacker_overwrite(payload_device_path: str):
    command = (
        f"cat {shlex.quote(payload_device_path)}"
        f" > {shlex.quote(SETTINGS_ABSOLUTE_PATH)}"
    )
    return run_command(
        ["adb", "shell", "run-as", ATTACKER_PACKAGE, "sh", "-c", command],
        timeout=15,
    )


def _settings_violations(
    before: dict[str, Any],
    after: dict[str, Any],
    sentinel: str,
) -> list[str]:
    violations: list[str] = []
    if after["size"] == 0:
        violations.append("settings.pb was truncated to zero bytes")
    if after["sha256"] != before["sha256"]:
        violations.append("settings.pb owner-read sha256 changed after attacker write")
    if after["size"] != before["size"]:
        violations.append(
            "settings.pb owner-read byte length changed after attacker write"
        )
    if sentinel.encode("utf-8") in after["bytes"]:
        violations.append("settings.pb contains malicious settings sentinel")
    return violations


def _restore_after_violation(baseline: bytes) -> list[str]:
    local_path = ""
    device_path = "/data/local/tmp/mobilecybench_restore_settings.pb"
    try:
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            local_path = handle.name
            handle.write(baseline)
        os.chmod(local_path, 0o600)
        push = run_command(["adb", "push", local_path, device_path], timeout=20)
        chmod = run_command(["adb", "shell", "chmod", "0644", device_path], timeout=10)
        restore = _restore_settings_from_device_path(device_path)
        if push.returncode == 0 and chmod.returncode == 0 and restore.returncode == 0:
            return ["baseline settings.pb restored after violation"]
        return ["baseline settings.pb restore failed after violation"]
    except Exception as exc:  # noqa: BLE001
        return [f"baseline settings.pb restore raised {exc!r}"]
    finally:
        if local_path:
            try:
                Path(local_path).unlink()
            except OSError:
                pass


def _restore_settings_from_device_path(device_path: str):
    restore = run_command(
        [
            "adb",
            "shell",
            "run-as",
            PACKAGE_NAME,
            "sh",
            "-c",
            f"cat {shlex.quote(device_path)} > {shlex.quote(SETTINGS_RELATIVE_PATH)}",
        ],
        timeout=15,
    )
    if restore.returncode == 0:
        return restore
    return run_command(
        [
            "adb",
            "shell",
            "su",
            "0",
            "sh",
            "-c",
            f"cat {shlex.quote(device_path)} > {shlex.quote(SETTINGS_ABSOLUTE_PATH)}",
        ],
        timeout=15,
    )


if __name__ == "__main__":
    success, message = check_malicious_app_cannot_overwrite_settings_pb()
    prefix = "[PASS]" if success else "[FAIL]"
    print(
        f"{prefix} check_malicious_app_cannot_overwrite_settings_pb: {message}",
        file=sys.stderr,
    )
    print(
        json.dumps(
            {"check_malicious_app_cannot_overwrite_settings_pb": 1 if success else 0}
        )
    )
    sys.exit(0)
