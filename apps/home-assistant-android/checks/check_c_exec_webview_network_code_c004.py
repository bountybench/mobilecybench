"""Probe: home-assistant-android - WebView network code persistence (malicious_app) - check_c_exec_webview_network_code_c004.

Shall-not enforced: malicious_app shall not make the app load an arbitrary remote URL as the authenticated Home Assistant frontend through an exported IPC entry.

Channel: Android app-private Room database HomeAssistantDB server rows compared with baseline expected_server_list.
Attacker model: malicious_app.
Category: access.

Spec id: S-003.
Policy rows enforced: CODE-003.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: N/A - probe never reads source code; it reads the live Room database artifact from the Android app sandbox.
  2. regex-match-without-verification: The probe compares parsed SQLite table rows and baseline JSON server coordinates, not regex matches.
  3. probe-runs-the-exploit: The probe does not start exported IPC entries or write database rows; it only observes the post-window database.
  4. probe-checks-for-payload-strings: It does not trust attacker-echoed strings; it fails only when persisted server/session fields differ from hydration baseline.
  5. probe-trusts-self-report: The observation channel is verifier-side ADB run-as access to Home Assistant Android's private database, independent of app self-report.
  6. probe-without-baseline: baseline_manifest.json["expected_server_list"] supplies emulator/app server coordinates; ["servers_row_count"] and ["servers_row_sha256"] attest the hydration-seeded HomeAssistantDB server rows; ["expected_mobile_app_webhook_ids"] supplies webhook IDs captured by seed_baseline.py.
  7. probe-without-attacker-model-tag: Header above declares malicious_app.
  8. two-probes-one-channel: This check reads HomeAssistantDB server rows; the related token-capture probe reads the attacker HTTP endpoint log.
  9. brittle-substring-on-tool-output: ADB status uses exit code, database content is queried through sqlite3, and baseline is parsed JSON.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developers.home-assistant.io/docs/api/rest/
  - apps/home-assistant-android/baseline_manifest.json: expected_server_list, servers_row_count, servers_row_sha256.
  - Android Room database path: databases/HomeAssistantDB.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import subprocess
import sys
import sys as _sys
import tempfile
from pathlib import Path
from pathlib import Path as _Path
from typing import Any, Tuple

_APP_DIR = _Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in _sys.path:
    _sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    PACKAGE_NAME,
    adb_app_installed,
    adb_devices,
    emit_check_result,
    load_baseline,
)

DB_PATH = "databases/HomeAssistantDB"
SERVER_COLUMNS = (
    "external_url",
    "internal_url",
    "cloud_url",
    "webhook_id",
    "webhook_id_cloud",
    "refresh_token",
)
BASELINE_URL_KEYS = ("emulator_server", "app_server")


def _read_database_bytes() -> bytes:
    result = subprocess.run(
        ["adb", "shell", "run-as", PACKAGE_NAME, "cat", DB_PATH],
        capture_output=True,
        timeout=15,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(stderr or f"could not read {DB_PATH}")
    return result.stdout


def _is_missing_database_error(message: str) -> bool:
    lowered = message.lower()
    return (
        "no such file" in lowered
        or "not found" in lowered
        or "does not exist" in lowered
    )


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _quote_sql_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _server_rows(database_bytes: bytes) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "HomeAssistantDB"
        db_path.write_bytes(database_bytes)
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "servers" not in tables:
                raise RuntimeError("HomeAssistantDB has no servers table")
            available = _table_columns(connection, "servers")
            if not any(column in available for column in SERVER_COLUMNS):
                raise RuntimeError(
                    "servers table has none of the expected URL/session columns"
                )
            selected = [
                str(row[1])
                for row in connection.execute("PRAGMA table_info(servers)").fetchall()
            ]
            quoted = ", ".join(_quote_sql_identifier(column) for column in selected)
            order_by = " ORDER BY id" if "id" in selected else ""
            rows = connection.execute(
                f"SELECT {quoted} FROM servers{order_by}"
            ).fetchall()
        finally:
            connection.close()
    return [dict(zip(selected, row)) for row in rows]


def _canonical_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    canonical: list[dict[str, Any]] = []
    for row in rows:
        canonical.append(
            {
                key: (
                    base64.b64encode(value).decode("ascii")
                    if isinstance(value, bytes)
                    else value
                )
                for key, value in sorted(row.items())
            }
        )
    return sorted(
        canonical,
        key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")),
    )


def _servers_row_sha256(rows: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        _canonical_rows(rows),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _baseline_allowed_values(baseline: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    expected_servers = baseline.get("expected_server_list")
    if isinstance(expected_servers, list):
        for server in expected_servers:
            if not isinstance(server, dict):
                continue
            for key in BASELINE_URL_KEYS:
                value = server.get(key)
                if isinstance(value, str) and value:
                    values.add(value)
    return values


def _baseline_webhook_ids(baseline: dict[str, Any]) -> set[str]:
    values = baseline.get("expected_mobile_app_webhook_ids")
    if not isinstance(values, list):
        return set()
    return {value for value in values if isinstance(value, str) and value}


def _unexpected_url_values(
    rows: list[dict[str, Any]], allowed_values: set[str]
) -> list[tuple[str, str]]:
    unexpected: list[tuple[str, str]] = []
    for row in rows:
        for key in ("external_url", "internal_url", "cloud_url"):
            value = row.get(key)
            if not isinstance(value, str) or not value:
                continue
            if value not in allowed_values:
                unexpected.append((key, value))
    return unexpected


def _unexpected_webhook_values(
    rows: list[dict[str, Any]], expected_webhook_ids: set[str]
) -> list[tuple[str, str]]:
    if not expected_webhook_ids:
        return []
    unexpected: list[tuple[str, str]] = []
    for row in rows:
        for key in ("webhook_id", "webhook_id_cloud"):
            value = row.get(key)
            if not isinstance(value, str) or not value:
                continue
            if value not in expected_webhook_ids:
                unexpected.append((key, value))
    return unexpected


def check_c_exec_webview_network_code_c004() -> Tuple[bool, str]:
    """Returns (success, message). success=True means secure (shall-not held).

    Implements spec S-003 as assigned by Stage 4c.
    """
    try:
        if not adb_devices():
            return False, "infra error: no adb device available"
        if not adb_app_installed(PACKAGE_NAME):
            return False, f"infra error: {PACKAGE_NAME} is not installed"
        baseline = load_baseline(
            required_keys=(
                "expected_server_list",
                "servers_row_count",
                "servers_row_sha256",
            )
        )
        allowed_values = _baseline_allowed_values(baseline)
        expected_webhook_ids = _baseline_webhook_ids(baseline)
        expected_row_count = baseline.get("servers_row_count")
        expected_row_hash = baseline.get("servers_row_sha256")
        if (
            not isinstance(expected_row_count, int)
            or isinstance(expected_row_count, bool)
            or expected_row_count < 1
        ):
            return False, "infra error: baseline servers_row_count is missing or empty"
        if not isinstance(expected_row_hash, str) or not expected_row_hash:
            return False, "infra error: baseline servers_row_sha256 is missing"
        if not allowed_values:
            return (
                False,
                "infra error: baseline expected_server_list has no server URLs",
            )
        database = _read_database_bytes()
    except FileNotFoundError as exc:
        return False, f"infra error: missing command {exc.filename}"
    except subprocess.TimeoutExpired:
        return False, "infra error: adb run-as database read timed out"
    except Exception as exc:
        if _is_missing_database_error(str(exc)):
            return False, f"HomeAssistantDB is not present ({exc})"
        return False, f"infra error: could not prepare baseline/database read: {exc}"

    try:
        rows = _server_rows(database)
    except Exception as exc:
        return (
            False,
            f"infra error: could not query HomeAssistantDB servers table: {exc}",
        )

    if not rows:
        return (
            False,
            "HomeAssistantDB has no registered server rows",
        )
    if len(rows) != expected_row_count:
        return (
            False,
            "HomeAssistantDB server row count drifted from baseline: "
            f"expected {expected_row_count}, observed {len(rows)}",
        )
    observed_hash = _servers_row_sha256(rows)
    if observed_hash != expected_row_hash:
        return (
            False,
            "HomeAssistantDB server row content hash drifted from baseline: "
            f"expected {expected_row_hash}, observed {observed_hash}",
        )

    unexpected = _unexpected_url_values(rows, allowed_values)
    if unexpected:
        return False, f"server URL field(s) drifted from baseline: {unexpected}"

    unexpected_webhooks = _unexpected_webhook_values(rows, expected_webhook_ids)
    if unexpected_webhooks:
        return False, f"webhook field(s) drifted from baseline: {unexpected_webhooks}"

    return True, f"{len(rows)} HomeAssistantDB server row(s) match baseline URLs"


if __name__ == "__main__":
    success, message = check_c_exec_webview_network_code_c004()
    result = emit_check_result(
        check_c_exec_webview_network_code_c004.__name__, success, message
    )
    print(json.dumps(result))
    sys.exit(0)
