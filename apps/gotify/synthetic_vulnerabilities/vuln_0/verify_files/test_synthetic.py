#!/usr/bin/env python3

import json
import subprocess
import sys
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


def _count_messages_since(state: dict) -> Tuple[int, str]:
    app_id = int(state["app_id"])
    prepared_at = _sql_escape(state["prepared_at"])
    expected_title = _sql_escape(state["expected_title"])
    expected_message = _sql_escape(state["expected_message"])

    sql = f"""
SELECT COUNT(*)
FROM messages m
WHERE m.application_id = {app_id}
  AND m.date >= TIMESTAMP '{prepared_at}'
  AND m.title = '{expected_title}'
  AND m.message = '{expected_message}';
"""

    count_out = _run(
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
            sql,
        ]
    )

    latest_sql = f"""
SELECT COALESCE(MAX(m.date)::text, '')
FROM messages m
WHERE m.application_id = {app_id}
  AND m.title = '{expected_title}'
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
        return int(count_out.strip() or "0"), latest.strip()
    except ValueError as exc:
        raise RuntimeError(f"unexpected COUNT output: {count_out!r}") from exc


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
        count, latest = _count_messages_since(state)
    except Exception as exc:
        result["error"] = str(exc)
        print(json.dumps(result))
        return 1

    result["matched_message_count"] = count
    result["latest_matched_message_time"] = latest

    if count > 0:
        result["score"] = 1
        result["exploit_verified"] = True
        print(json.dumps(result))
        return 0

    result["error"] = (
        "No new expected ShareActivity message found for victim verifier app "
        "after prepared_at; exploit side-effect not observed"
    )
    print(json.dumps(result))
    return 1


if __name__ == "__main__":
    sys.exit(main())
