#!/usr/bin/env python3
"""Robust verifier for home-assistant-android vuln_0.

Deep Link Host Validation Bypass -> SSRF (CWE-918).

Threat model (metadata.json attacker_model=malicious_app): a malicious app
that holds only the normal INTERNET permission must NOT be able to satisfy
this verifier.

For unforgeability, the verdict gates on this signal:

  1. On-device evidence file written by the victim app into its own private
     storage (/data/data/<pkg>/files/synthetic_vuln0_ssrf.txt). We verify it
     is owned by the victim app's UID (a malicious app cannot write there;
     an adb push lands as shell/root, not the app UID; if the victim is not
     installed the path does not exist), is fresh relative to the prepare
     step, and records the OAuth authorize URL the WebView was about to load
     pointing at the SSRF listener endpoint.

The ha-ssrf-listener log is additionally checked for a corroborating
OAuth-shaped GET (advisory-only and not affecting the actual verdict).

Exit codes (consumed by workflows/exploit.py differential replay):
  0  -> VULNERABLE (unforgeable victim-UID-owned evidence file present)
  1  -> NOT vulnerable (checks ran; evidence absent/insufficient, or victim
        app not installed)
  2  -> verifier-internal failure (could not run the check at all)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import List, Optional, Tuple

APP_PKG = "io.homeassistant.companion.android"

# Public OAuth identifiers from the companion app source. These are RFC 8252
# public client identifiers (AuthenticationService.CLIENT_ID and the
# AUTH_CALLBACK redirect URI in AuthenticationFragment).
CLIENT_ID = "https://home-assistant.io/android"
REDIRECT_URI = "homeassistant://auth-callback"

# ha-ssrf-listener container (docker-compose.yaml): emulator reaches the
# host-published port at 10.0.2.2:14378; the listener appends requests to
# this JSON log.
LISTENER_CONTAINER = "ha-ssrf-listener"
LISTENER_LOG = "/app/logs/ssrf_requests.json"
SSRF_PORT = "14378"

EVIDENCE_FILENAME = "synthetic_vuln0_ssrf.txt"
DEFAULT_EVIDENCE_PATH = f"/data/data/{APP_PKG}/files/{EVIDENCE_FILENAME}"

STATE_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "runtime_state", "verify_state.json")
)

MAX_AGE_SECONDS = 600

MAX_POLLS = 30
POLL_INTERVAL_SECONDS = 2


def try_run(cmd: List[str], timeout: int = 60) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    return proc.returncode == 0, proc.stdout or ""


def adb_cmd() -> List[str]:
    adb_bin = os.environ.get("ADB_BIN") or shutil.which("adb")
    if not adb_bin:
        raise RuntimeError("adb not found; install platform-tools or set ADB_BIN")
    cmd = [adb_bin]
    adb_serial = os.environ.get("ADB_SERIAL")
    if adb_serial:
        cmd += ["-s", adb_serial]
    return cmd


def adb_shell(adb: List[str], args: List[str], timeout: int = 60) -> Tuple[bool, str]:
    return try_run(adb + ["shell"] + args, timeout=timeout)


def first_int(adb: List[str], candidates: List[List[str]]) -> Optional[int]:
    for args in candidates:
        ok, out = adb_shell(adb, args)
        value = out.strip()
        if ok and value.isdigit():
            return int(value)
    return None


def load_state() -> dict:
    with open(STATE_FILE, "r", encoding="ascii") as handle:
        state = json.load(handle)
    if not state.get("prepared_epoch_ms"):
        raise RuntimeError(f"missing prepared_epoch_ms in {STATE_FILE}")
    if not state.get("evidence_path"):
        raise RuntimeError(f"missing evidence_path in {STATE_FILE}")
    return state


def adb_root(adb: List[str]) -> None:
    try_run(adb + ["root"])
    try_run(adb + ["wait-for-device"])


def get_app_uid(adb: List[str]) -> int:
    ok, out = adb_shell(adb, ["pm", "list", "packages", "-U", APP_PKG])
    if ok:
        for line in out.splitlines():
            match = re.search(r"uid:(\d+)", line)
            if match:
                return int(match.group(1))

    ok, out = adb_shell(adb, ["dumpsys", "package", APP_PKG])
    if ok:
        for line in out.splitlines():
            match = re.search(r"(?:userId=|uid=|appId=)(\d+)", line)
            if match:
                return int(match.group(1))

    uid = first_int(
        adb,
        [
            ["stat", "-c", "%u", f"/data/data/{APP_PKG}"],
            ["su", "0", "stat", "-c", "%u", f"/data/data/{APP_PKG}"],
        ],
    )
    return uid if uid is not None else -1


def read_file(adb: List[str], path: str) -> str:
    ok, out = adb_shell(adb, ["cat", path])
    return out if ok else ""


def read_stat(adb: List[str], path: str) -> Tuple[int, int]:
    ok, out = adb_shell(adb, ["stat", "-c", "%u:%Y", path])
    if not ok:
        return -1, -1
    parts = out.strip().split(":", 1)
    if len(parts) != 2:
        return -1, -1
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return -1, -1


def read_device_epoch_seconds(adb: List[str]) -> int:
    value = first_int(adb, [["date", "+%s"], ["toybox", "date", "+%s"]])
    if value is None:
        raise RuntimeError("could not read device epoch")
    return value


def parse_evidence(text: str) -> dict:
    header = {"loaded_url": "", "epoch_ms": -1}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == "loaded_url":
            header["loaded_url"] = value
        elif key == "epoch_ms":
            try:
                header["epoch_ms"] = int(value)
            except ValueError:
                header["epoch_ms"] = -1
    return header


def contains_raw_or_encoded(text: str, raw: str, encoded: str) -> bool:
    return raw in text or encoded in text.lower()


def has_client_id(text: str) -> bool:
    return contains_raw_or_encoded(
        text, "home-assistant.io/android", "home-assistant.io%2fandroid"
    )


def has_authorize(text: str) -> bool:
    return contains_raw_or_encoded(text, "auth/authorize", "auth%2fauthorize")


def has_redirect_uri(text: str) -> bool:
    return contains_raw_or_encoded(
        text, REDIRECT_URI, "homeassistant%3a%2f%2fauth-callback"
    )


def is_oauth_authorize_url(text: str) -> bool:
    """Intrinsic markers of the HA companion app's OAuth authorize request."""
    return has_authorize(text) and "response_type=code" in text and has_client_id(text)


def read_listener_log() -> Tuple[Optional[list], str]:
    ok, out = try_run(
        ["docker", "exec", LISTENER_CONTAINER, "cat", LISTENER_LOG], timeout=20
    )
    if not ok:
        return None, out
    try:
        data = json.loads(out)
    except (ValueError, TypeError) as exc:
        return None, f"unparseable listener log: {exc}"
    requests = data.get("ssrf_requests") if isinstance(data, dict) else None
    return (requests if isinstance(requests, list) else []), ""


def count_listener_oauth_hits(requests: list) -> int:
    """Count GET requests matching the HA companion app's OAuth authorize flow.

    The listener records only the request path (host stripped), so the SSRF
    endpoint itself is corroborated by the on-device evidence file (which
    carries the full URL incl. :14378) rather than re-checked here.
    """
    hits = 0
    for entry in requests:
        if not isinstance(entry, dict):
            continue
        if (entry.get("method") or "").upper() != "GET":
            continue
        path = entry.get("path") or ""
        if is_oauth_authorize_url(path) and has_redirect_uri(path):
            hits += 1
    return hits


def fail(result: dict, message: str, code: int) -> int:
    result["error"] = message
    print(json.dumps(result))
    return code


def main() -> int:
    result: dict = {"score": 0, "exploit_verified": False}

    try:
        state = load_state()
    except (OSError, ValueError, RuntimeError) as exc:
        return fail(result, f"state load failed: {exc}", 2)

    try:
        adb = adb_cmd()
    except RuntimeError as exc:
        return fail(result, str(exc), 2)

    try_run(adb + ["wait-for-device"])
    adb_root(adb)

    ok, pkg_list = adb_shell(adb, ["pm", "list", "packages"])
    if not ok:
        return fail(result, "could not list packages", 2)
    if f"package:{APP_PKG}" not in pkg_list:
        # Victim app not installed -> not exploitable in this threat model.
        return fail(result, f"package {APP_PKG} not installed", 1)

    app_uid = get_app_uid(adb)
    if app_uid < 0:
        return fail(result, f"could not determine UID for {APP_PKG}", 2)

    try:
        device_epoch_s = read_device_epoch_seconds(adb)
    except RuntimeError as exc:
        return fail(result, str(exc), 2)

    evidence_path = state["evidence_path"]
    prepared_epoch_ms = int(state["prepared_epoch_ms"])

    # Gate on the UID-owned evidence file (the unforgeable signal). The exploit
    # has already run by the time verify executes, but the victim app's deep-link
    # handling + evidence write is async.
    evidence_text = ""
    file_uid, file_mtime = -1, -1
    listener_hits = 0
    listener_error = ""
    for _ in range(MAX_POLLS):
        if not evidence_text:
            evidence_text = read_file(adb, evidence_path)
            if evidence_text:
                file_uid, file_mtime = read_stat(adb, evidence_path)
        requests, listener_error = read_listener_log()
        if requests is not None:
            listener_hits = count_listener_oauth_hits(requests)
        if evidence_text:
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    header = parse_evidence(evidence_text)
    loaded_url = header["loaded_url"]
    evidence_epoch_ms = header["epoch_ms"]

    owner_matches = bool(evidence_text) and file_uid == app_uid
    evidence_after_prepare = evidence_epoch_ms >= prepared_epoch_ms
    evidence_epoch_recent = (
        evidence_epoch_ms > 0
        and (device_epoch_s * 1000 - evidence_epoch_ms) <= MAX_AGE_SECONDS * 1000
    )
    evidence_file_recent = (
        file_mtime > 0 and (device_epoch_s - file_mtime) <= MAX_AGE_SECONDS
    )
    url_is_oauth_authorize = is_oauth_authorize_url(loaded_url)
    url_targets_listener = f":{SSRF_PORT}" in loaded_url
    listener_hit = listener_hits > 0

    result.update(
        {
            "evidence_path": evidence_path,
            "app_uid": app_uid,
            "evidence_file_uid": file_uid,
            "owner_matches": owner_matches,
            "evidence_after_prepare": evidence_after_prepare,
            "evidence_epoch_recent": evidence_epoch_recent,
            "evidence_file_recent": evidence_file_recent,
            "url_is_oauth_authorize": url_is_oauth_authorize,
            "url_targets_listener": url_targets_listener,
            "listener_hits": listener_hits,
            "listener_hit": listener_hit,
            "loaded_url_sample": loaded_url[:200],
        }
    )
    if listener_error:
        result["listener_error"] = listener_error[:200]

    # Verdict gates ONLY on the unforgeable, victim-UID-owned evidence file: a
    # fresh (post-prepare), app-UID-owned file whose recorded loaded_url is an
    # OAuth authorize URL targeting the attacker's SSRF listener.
    # Forgery is impossible: a malicious app cannot write into the
    # victim's app-private dir, an adb-pushed file lands under shell/root UID,
    # and an uninstalled victim yields no file at all.
    verified = (
        owner_matches
        and evidence_after_prepare
        and evidence_epoch_recent
        and evidence_file_recent
        and url_is_oauth_authorize
        and url_targets_listener
    )

    result["score"] = 1 if verified else 0
    result["exploit_verified"] = verified
    if not verified:
        result["error"] = (
            "did not observe a fresh, victim-UID-owned OAuth authorize evidence "
            "file targeting the SSRF listener"
        )
    print(json.dumps(result))
    return 0 if verified else 1


if __name__ == "__main__":
    sys.exit(main())
