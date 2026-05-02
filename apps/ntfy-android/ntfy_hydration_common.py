#!/usr/bin/env python3
"""Shared helpers for ntfy-android hydration scripts."""

from __future__ import annotations

import base64
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


class CommandError(RuntimeError):
    """Raised when a shell command fails under check=True."""

    def __init__(self, cmd: list[str], returncode: int, stdout: str, stderr: str):
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            f"command failed ({returncode}): {' '.join(cmd)}\nstdout={stdout[:500]}\nstderr={stderr[:500]}"
        )


def run(
    cmd: list[str],
    *,
    input_text: str | None = None,
    timeout: int = 30,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise CommandError(
            cmd, result.returncode, result.stdout or "", result.stderr or ""
        )
    return result


def adb(
    args: list[str],
    *,
    input_text: str | None = None,
    timeout: int = 30,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return run(["adb", *args], input_text=input_text, timeout=timeout, check=check)


def adb_ok() -> bool:
    try:
        result = adb(["get-state"], timeout=5)
        return result.returncode == 0 and result.stdout.strip().startswith("device")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def adb_root_shell(
    script: str, *, timeout: int = 30, check: bool = False
) -> subprocess.CompletedProcess[str]:
    return adb(
        ["shell", "su", "0", "sh"], input_text=script, timeout=timeout, check=check
    )


def adb_file_exists(path: str) -> bool:
    result = adb(["shell", "su", "0", "test", "-f", path], timeout=10)
    return result.returncode == 0


def adb_sql(
    db_path: str, sql: str, *, timeout: int = 30, check: bool = False
) -> subprocess.CompletedProcess[str]:
    return adb(
        ["shell", "su", "0", "sqlite3", db_path],
        input_text=sql,
        timeout=timeout,
        check=check,
    )


def adb_sql_lines(db_path: str, sql: str, *, timeout: int = 30) -> list[str]:
    result = adb_sql(
        db_path, sql if sql.rstrip().endswith(";") else sql + ";", timeout=timeout
    )
    if result.returncode != 0:
        return []
    return [
        line.strip().replace("\r", "")
        for line in result.stdout.splitlines()
        if line.strip()
    ]


def adb_sql_scalar(db_path: str, sql: str, *, timeout: int = 30) -> str:
    lines = adb_sql_lines(db_path, sql, timeout=timeout)
    return lines[0] if lines else ""


def sql_quote(value: Any) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def http_request(
    method: str,
    url: str,
    *,
    data: str | bytes | None = None,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: int = 10,
) -> tuple[int, str]:
    body: bytes | None
    if isinstance(data, str):
        body = data.encode("utf-8")
    else:
        body = data
    req_headers = dict(headers or {})
    if auth:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode("utf-8")).decode("ascii")
        req_headers["Authorization"] = f"Basic {token}"
    request = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(
            request, timeout=timeout
        ) as response:  # noqa: S310 - local fixture URL
            text = response.read().decode("utf-8", errors="replace")
            return int(response.status), text
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return int(exc.code), text
    except urllib.error.URLError as exc:
        return 0, f"unreachable:{exc}"


def http_get(
    url: str, *, auth: tuple[str, str] | None = None, timeout: int = 10
) -> tuple[int, str]:
    return http_request("GET", url, auth=auth, timeout=timeout)


def http_post(
    url: str,
    data: str,
    *,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: int = 10,
) -> tuple[int, str]:
    req_headers = {"Content-Type": "text/plain; charset=utf-8"}
    req_headers.update(headers or {})
    return http_request(
        "POST", url, data=data, headers=req_headers, auth=auth, timeout=timeout
    )


def ndjson_messages(text: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("event", "message") == "message":
            messages.append(item)
    return messages


def sha256_prefix(value: str, length: int = 12) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]
