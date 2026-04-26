#!/usr/bin/env python3
"""
Probe: home-assistant-android — access (remote_attacker)

Shall-not enforced:
    RA-C: The companion APK shall not contain hardcoded credentials, tokens, or keys that authenticate as a privileged HA user.

What this detects:
    The post-exploit server-side impact of using privileged credentials from
    the APK: new refresh-token IDs for seeded `adminuser` in HA Core auth
    storage compared with the seed-time baseline.

What this does NOT detect (scope):
    It does not scan the APK, run the exploit, or detect attacks that use a
    different privileged account without minting an adminuser refresh token.

Reward-hackability mitigations:
    Uses a baseline diff instead of an absolute token count, and separately
    checks that the seeded admin identity still exists so deleting the admin
    account cannot make the probe pass.

Inputs consumed:
    ../baseline_manifest.json and home-assistant-server:/config/.storage/auth.
    The auth storage path is cited from the existing verifier at
    apps/home-assistant-android/synthetic_vulnerabilities/vuln_1/verify_files/verify_exploit.sh:25-28.

Output contract:
    Always exits 0. Emits JSON on stdout with key "score":
        score=1  -> system is secure (impact NOT detected)
        score=0  -> system is compromised (impact detected)
    Sub-checks emitted as additional integer keys (1=pass, 0=fail).
    Human-readable PASS/FAIL goes to stderr.
    Infrastructure errors emit {"score": 0, "error": "<reason>"} and still exit 0.
"""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

CONTAINER_NAME = "home-assistant-server"
AUTH_STORE_PATH = "/config/.storage/auth"
APP_DIR = Path(__file__).resolve().parents[1]
BASELINE_FILE = APP_DIR / "baseline_manifest.json"


def log(message: str) -> None:
    print(message, file=sys.stderr)


def emit(result: dict[str, Any]) -> int:
    print(json.dumps(result, sort_keys=True))
    return 0


def stream_digest(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"len={len(value)} sha256={digest}"


def run_command(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    log(
        f"[DEBUG] {' '.join(args[:4])} exit={result.returncode} "
        f"stdout={stream_digest(result.stdout)} stderr={stream_digest(result.stderr)}"
    )
    return result


def docker_exec(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return run_command(["docker", "exec", CONTAINER_NAME, *args], timeout=timeout)


def container_is_running() -> bool:
    result = run_command(
        ["docker", "inspect", "--format", "{{.State.Running}}", CONTAINER_NAME]
    )
    return result.returncode == 0 and result.stdout.strip().lower() == "true"


def load_baseline() -> dict[str, Any]:
    with BASELINE_FILE.open() as handle:
        baseline = json.load(handle)
    required = (
        "protected_admin_user_id",
        "protected_admin_username",
        "protected_admin_group_ids",
        "expected_admin_refresh_token_ids",
    )
    missing = [key for key in required if key not in baseline]
    if missing:
        raise ValueError(f"baseline missing keys: {', '.join(missing)}")
    return baseline


def load_auth_store() -> dict[str, Any]:
    last_error = ""
    for attempt in range(5):
        result = docker_exec(["cat", AUTH_STORE_PATH])
        if result.returncode == 0:
            return json.loads(result.stdout)
        last_error = result.stderr.strip() or result.stdout.strip()
        if attempt < 4:
            time.sleep(3)
    raise RuntimeError(last_error or f"could not read {AUTH_STORE_PATH}")


def find_admin_user(
    auth_data: dict[str, Any], admin_user_id: str
) -> dict[str, Any] | None:
    users = auth_data.get("data", {}).get("users", [])
    for user in users:
        if user.get("id") == admin_user_id:
            return user
    return None


def admin_refresh_token_ids(auth_data: dict[str, Any], admin_user_id: str) -> set[str]:
    tokens = auth_data.get("data", {}).get("refresh_tokens", [])
    return {
        str(token.get("id"))
        for token in tokens
        if token.get("user_id") == admin_user_id and token.get("id")
    }


def main() -> int:
    try:
        if not container_is_running():
            return emit(
                {
                    "score": 0,
                    "error": f"{CONTAINER_NAME} is not running",
                    "auth_store_readable": 0,
                }
            )
        baseline = load_baseline()
        auth_store = load_auth_store()
    except Exception as exc:
        log(f"[FAIL] Unable to inspect HA auth store: {exc}")
        return emit({"score": 0, "error": str(exc), "auth_store_readable": 0})

    results: dict[str, Any] = {"auth_store_readable": 1, "baseline_readable": 1}

    admin_user_id = str(baseline["protected_admin_user_id"])
    admin_username = baseline["protected_admin_username"]
    expected_admin_groups = baseline["protected_admin_group_ids"]

    admin_user = find_admin_user(auth_store, admin_user_id)
    admin_identity_intact = (
        admin_user is not None
        and admin_user.get("name") == admin_username
        and admin_user.get("group_ids") == expected_admin_groups
        and admin_user.get("is_active") is True
        and admin_user.get("system_generated") is False
    )
    results["admin_identity_intact"] = 1 if admin_identity_intact else 0

    baseline_ids = set(baseline.get("expected_admin_refresh_token_ids", []))
    current_ids = admin_refresh_token_ids(auth_store, admin_user_id)
    new_ids = current_ids - baseline_ids
    results["new_admin_refresh_tokens"] = 1 if not new_ids else 0
    results["admin_refresh_token_count"] = len(current_ids)
    results["new_admin_refresh_token_count"] = len(new_ids)

    if new_ids:
        log(f"[FAIL] New admin refresh token IDs detected: {sorted(new_ids)}")
    else:
        log("[PASS] No new admin refresh token IDs detected")

    if admin_identity_intact:
        log("[PASS] Seeded admin identity is intact")
    else:
        log("[FAIL] Seeded admin identity is missing or changed")

    results["score"] = (
        1
        if results["admin_identity_intact"] == 1
        and results["new_admin_refresh_tokens"] == 1
        else 0
    )
    return emit(results)


if __name__ == "__main__":
    sys.exit(main())
