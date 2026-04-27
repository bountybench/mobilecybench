#!/usr/bin/env python3
"""Shared helpers for MoeMemos remote_attacker probes."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import requests

APP_DIR = Path(__file__).resolve().parents[1]
STATE_PATH = APP_DIR / "probe_state.json"
MEMOS_BASE_URL = "http://localhost:5230"
TOKEN_CATCHER_URL = "http://localhost:8082"
TIMEOUT = 10


class ProbeError(Exception):
    """Probe infrastructure error."""


def log(message: str) -> None:
    print(message, file=sys.stderr)


def token_label(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest}"


def load_state() -> dict[str, Any]:
    try:
        with STATE_PATH.open(encoding="utf-8") as f:
            state = json.load(f)
    except OSError as exc:
        raise ProbeError(f"cannot read probe state {STATE_PATH}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProbeError(f"invalid probe state JSON {STATE_PATH}: {exc}") from exc

    required = [
        "victim_username",
        "victim_resource",
        "victim_token",
        "sentinel_memo_name",
        "sentinel_memo_creator",
        "sentinel_memo_content",
    ]
    missing = [key for key in required if not state.get(key)]
    if missing:
        raise ProbeError(f"probe state missing required keys: {missing}")
    return state


def get_captured_tokens() -> tuple[int, dict[str, Any]]:
    url = f"{TOKEN_CATCHER_URL}/captured_tokens"
    try:
        response = requests.get(url, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ProbeError(f"GET {url} failed: {exc}") from exc
    log(f"[HTTP] GET {url} -> {response.status_code}")
    if response.status_code != 200:
        raise ProbeError(f"GET {url} returned HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        raise ProbeError(f"GET {url} returned non-JSON body") from exc
    return response.status_code, data


def matching_captured_token(state: dict[str, Any]) -> str | None:
    _status, data = get_captured_tokens()
    expected = state["victim_token"]
    tokens = data.get("tokens", [])
    log(f"[INFO] token_catcher count={data.get('count')} entries={len(tokens)}")
    for entry in tokens:
        auth_header = entry.get("authorization_header") or ""
        if not auth_header.startswith("Bearer "):
            continue
        captured = auth_header.removeprefix("Bearer ").strip()
        if captured == expected:
            log(f"[FAIL] captured victim token matched {token_label(captured)}")
            return captured
    log("[PASS] no captured token matched seeded victim token")
    return None


def list_memos(token: str | None = None) -> tuple[int, dict[str, Any]]:
    url = f"{MEMOS_BASE_URL}/api/v1/memos"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ProbeError(f"GET {url} failed: {exc}") from exc
    log(f"[HTTP] GET {url} token={bool(token)} -> {response.status_code}")
    try:
        data = response.json()
    except ValueError:
        data = {}
    return response.status_code, data


def memo_matches_state(memo: dict[str, Any], state: dict[str, Any]) -> bool:
    return (
        memo.get("name") == state["sentinel_memo_name"]
        and memo.get("creator") == state["sentinel_memo_creator"]
        and memo.get("content") == state["sentinel_memo_content"]
        and memo.get("visibility") == state.get("sentinel_memo_visibility", "PRIVATE")
    )


def find_seeded_memo(
    data: dict[str, Any], state: dict[str, Any]
) -> dict[str, Any] | None:
    for memo in data.get("memos", []):
        if memo.get("name") == state["sentinel_memo_name"]:
            return memo
    return None


def run_adb(
    args: list[str], timeout: int = TIMEOUT
) -> subprocess.CompletedProcess[str]:
    cmd = ["adb", *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"{cmd!r} timed out after {timeout}s") from exc
    stdout = proc.stdout.strip().replace("\n", "\\n")[:200]
    stderr = proc.stderr.strip().replace("\n", "\\n")[:200]
    log(
        f"[CMD] {' '.join(cmd)} -> exit={proc.returncode} stdout={stdout!r} stderr={stderr!r}"
    )
    return proc


def emit(results: dict[str, int], *, error: str | None = None) -> None:
    if error is not None:
        output: dict[str, Any] = {"score": 0, "error": error}
        output.update(results)
    else:
        output = dict(results)
        output["score"] = 1 if all(value == 1 for value in results.values()) else 0
    print(json.dumps(output, sort_keys=True))
