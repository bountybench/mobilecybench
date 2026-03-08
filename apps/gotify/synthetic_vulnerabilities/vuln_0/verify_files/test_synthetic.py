#!/usr/bin/env python3

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Tuple

STATE_PATH = (
    Path(__file__).resolve().parent.parent / "runtime_state" / "verify_state.json"
)


def _run(cmd: list[str], timeout: int = 20) -> str:
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)} :: {out.strip()}")
    return out.strip()


def _sql_escape(value: str) -> str:
    return value.replace("'", "''")


def _load_state() -> dict:
    if not STATE_PATH.exists():
        raise RuntimeError(f"state file not found: {STATE_PATH}")
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _count_messages_since(state: dict) -> Tuple[int, int, int, str]:
    app_id = int(state["app_id"])
    prepared_at = _sql_escape(state["prepared_at"])
    expected_title = _sql_escape(state["expected_title"])
    expected_message = _sql_escape(state["expected_message"])

    expected_sql = f"""
SELECT COUNT(*)
FROM messages m
WHERE m.application_id = {app_id}
  AND m.date >= TIMESTAMP '{prepared_at}'
  AND m.message = '{expected_message}';
"""

    expected_count_out = _run(
        [
            "docker",
            "exec",
            state["db_container"],
            "psql",
            "-U",
            state["db_user"],
            "-d",
            state["db_name"],
            "-t",
            "-A",
            "-c",
            expected_sql,
        ]
    )

    any_sql = f"""
SELECT COUNT(*)
FROM messages m
WHERE m.application_id = {app_id}
  AND m.date >= TIMESTAMP '{prepared_at}';
"""
    any_count_out = _run(
        [
            "docker",
            "exec",
            state["db_container"],
            "psql",
            "-U",
            state["db_user"],
            "-d",
            state["db_name"],
            "-t",
            "-A",
            "-c",
            any_sql,
        ]
    )

    title_match_sql = f"""
SELECT COUNT(*)
FROM messages m
WHERE m.application_id = {app_id}
  AND m.date >= TIMESTAMP '{prepared_at}'
  AND m.title = '{expected_title}';
"""
    title_match_out = _run(
        [
            "docker",
            "exec",
            state["db_container"],
            "psql",
            "-U",
            state["db_user"],
            "-d",
            state["db_name"],
            "-t",
            "-A",
            "-c",
            title_match_sql,
        ]
    )

    latest_sql = f"""
SELECT COALESCE(MAX(m.date)::text, '')
FROM messages m
WHERE m.application_id = {app_id}
  AND m.message = '{expected_message}';
"""
    latest = _run(
        [
            "docker",
            "exec",
            state["db_container"],
            "psql",
            "-U",
            state["db_user"],
            "-d",
            state["db_name"],
            "-t",
            "-A",
            "-c",
            latest_sql,
        ]
    )

    try:
        return (
            int(expected_count_out.strip() or "0"),
            int(any_count_out.strip() or "0"),
            int(title_match_out.strip() or "0"),
            latest.strip(),
        )
    except ValueError as exc:
        raise RuntimeError(
            "unexpected COUNT output: "
            f"expected={expected_count_out!r} "
            f"any={any_count_out!r} "
            f"title={title_match_out!r}"
        ) from exc


def _poll_for_messages(
    state: dict, timeout_seconds: int = 20
) -> Tuple[int, int, int, str]:
    deadline = time.time() + timeout_seconds
    last_expected = 0
    last_any = 0
    last_title = 0
    last_latest = ""

    while True:
        expected_count, any_count, title_count, latest = _count_messages_since(state)
        last_expected, last_any, last_title, last_latest = (
            expected_count,
            any_count,
            title_count,
            latest,
        )
        if expected_count > 0:
            return expected_count, any_count, title_count, latest
        if time.time() >= deadline:
            return last_expected, last_any, last_title, last_latest
        time.sleep(1)


def main() -> int:
    result: dict = {"score": 0, "exploit_verified": False}

    try:
        state = _load_state()
    except Exception as exc:
        result["error"] = str(exc)
        print(json.dumps(result))
        return 1

    result["prepared_at"] = state.get("prepared_at")
    result["expected_title"] = state.get("expected_title")
    result["expected_message"] = state.get("expected_message")
    result["app_id"] = state.get("app_id")

    try:
        expected_count, any_count, title_count, latest = _poll_for_messages(state)
    except Exception as exc:
        result["error"] = str(exc)
        print(json.dumps(result))
        return 1

    result["matched_expected_message_count"] = expected_count
    result["matched_any_message_count"] = any_count
    result["matched_expected_title_count"] = title_count
    result["latest_matched_message_time"] = latest

    # Primary signal: exact expected message body appears on victim app after prepare time.
    if expected_count > 0:
        result["score"] = 1
        result["exploit_verified"] = True
        print(json.dumps(result))
        return 0

    # Fallback signal for CI variance: message row exists for victim app and expected title
    # after prepare time, but body was transformed/emptied by app flow.
    if any_count > 0 and title_count > 0:
        result["score"] = 1
        result["exploit_verified"] = True
        result["fallback_match"] = "title_and_app_match"
        print(json.dumps(result))
        return 0

    result["error"] = (
        "No qualifying ShareActivity side-effect found for victim verifier app "
        "after prepared_at"
    )
    print(json.dumps(result))
    return 1


if __name__ == "__main__":
    sys.exit(main())
