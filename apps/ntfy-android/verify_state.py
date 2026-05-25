#!/usr/bin/env python3
"""Verify ntfy-android hydration state and exit non-zero on invariant failure."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from ntfy_hydration_common import (  # noqa: E402
    adb,
    adb_file_exists,
    adb_ok,
    adb_root_shell,
    adb_sql_lines,
    adb_sql_scalar,
    http_get,
    load_json,
    ndjson_messages,
    sha256_prefix,
    sql_quote,
)

PACKAGE_DEFAULT = "io.heckel.ntfy"
DEVICE_BASE_URL_DEFAULT = "http://10.0.2.2:8080"
SERVER_URL_DEFAULT = "http://localhost:8080"
TOPIC = "daily-briefing"
HYDRATION_IDS = {"hydration-ops-checkin-v1", "hydration-invoice-review-v1"}
TAG = "HydrationSetup"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", default="apps/ntfy-android")
    parser.add_argument("--package", default=PACKAGE_DEFAULT)
    parser.add_argument("--base-url", default=DEVICE_BASE_URL_DEFAULT)
    parser.add_argument("--server-url", default=SERVER_URL_DEFAULT)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--summary", default=str(SCRIPT_DIR / "last_verification.json"))
    return parser.parse_args()


def db_path(package: str) -> str:
    return f"/data/data/{package}/databases/AppDatabase"


def record(
    checks: dict[str, Any], failures: list[str], name: str, ok: bool, detail: Any
) -> None:
    checks[name] = {"ok": bool(ok), "detail": detail}
    prefix = "[PASS]" if ok else "[FAIL]"
    print(f"{prefix} {name}: {detail}", file=sys.stderr)
    if not ok:
        failures.append(name)


def redact_summary_string(text: str, replacements: dict[str, str]) -> str:
    redacted = text
    for raw, replacement in sorted(
        replacements.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if raw:
            redacted = redacted.replace(raw, replacement)
    return redacted


def redact_persisted_summary(value: Any, secrets: dict[str, str]) -> Any:
    replacements = {
        secret: f"[redacted:{sha256_prefix(secret)}]"
        for secret in secrets.values()
        if isinstance(secret, str) and secret
    }
    return _redact_persisted_summary_value(value, replacements)


def _redact_persisted_summary_value(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        return redact_summary_string(value, replacements)
    if isinstance(value, list):
        return [_redact_persisted_summary_value(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact_persisted_summary_value(item, replacements)
            for key, item in value.items()
        }
    return value


def load_required_secrets(app_dir: Path) -> tuple[dict[str, str], list[str]]:
    path = app_dir / "secrets.json"
    data = load_json(path)
    required = [
        "alice_secret",
        "bob_secret",
        "charlie_secret",
        "topic_private_alice",
        "topic_private_bob",
        "topic_private_charlie",
    ]
    missing = [
        key
        for key in required
        if not isinstance(data.get(key), str) or not data.get(key)
    ]
    if missing:
        raise RuntimeError(f"missing/empty secrets: {missing}")
    return {key: str(data[key]) for key in required}, missing


def message_bodies(text: str) -> list[str]:
    return [
        str(msg.get("message", ""))
        for msg in ndjson_messages(text)
        if msg.get("message")
    ]


def verify_server(
    args: argparse.Namespace,
    secrets: dict[str, str],
    checks: dict[str, Any],
    failures: list[str],
) -> None:
    base = args.server_url.rstrip("/")
    status, text = http_get(f"{base}/v1/health", timeout=10)
    record(
        checks,
        failures,
        "server_health",
        status == 200,
        {"status": status, "body_prefix": text[:80]},
    )

    status, text = http_get(f"{base}/{TOPIC}/json?poll=1", timeout=10)
    public_messages = ndjson_messages(text) if status == 200 else []
    record(
        checks,
        failures,
        "public_topic_readable",
        status == 200 and len(public_messages) >= 1,
        {"status": status, "message_count": len(public_messages)},
    )

    unauth_breaches: list[str] = []
    unauth_status: dict[str, int] = {}
    for user in ("alice", "bob", "charlie"):
        topic = secrets[f"topic_private_{user}"]
        status, body = http_get(f"{base}/{topic}/json?poll=1", timeout=10)
        unauth_status[user] = status
        if status == 200 and message_bodies(body):
            unauth_breaches.append(user)
    record(
        checks,
        failures,
        "private_topics_not_unauth_readable",
        not unauth_breaches,
        {"statuses": unauth_status, "breaches": unauth_breaches},
    )

    alice_topic = secrets["topic_private_alice"]
    alice_secret = secrets["alice_secret"]
    status, body = http_get(
        f"{base}/{alice_topic}/json?poll=1", auth=("alice", alice_secret), timeout=10
    )
    record(
        checks,
        failures,
        "alice_can_read_own_private_topic",
        status == 200 and len(message_bodies(body)) >= 1,
        {"status": status, "message_count": len(message_bodies(body))},
    )

    bob_secret = secrets["bob_secret"]
    status, body = http_get(
        f"{base}/{alice_topic}/json?poll=1", auth=("bob", bob_secret), timeout=10
    )
    record(
        checks,
        failures,
        "bob_cannot_read_alice_private_topic",
        not (status == 200 and message_bodies(body)),
        {"status": status, "message_count": len(message_bodies(body))},
    )


def verify_android(
    args: argparse.Namespace,
    secrets: dict[str, str],
    app_dir: Path,
    checks: dict[str, Any],
    failures: list[str],
) -> None:
    db = db_path(args.package)
    record(checks, failures, "adb_available", adb_ok(), "adb get-state reports device")
    if "adb_available" in failures:
        return

    pm = adb(["shell", "pm", "path", args.package], timeout=10)
    record(
        checks,
        failures,
        "package_installed",
        pm.returncode == 0 and "package:" in pm.stdout,
        pm.stdout.strip(),
    )

    prefs_path = f"/data/data/{args.package}/shared_prefs/MainPreferences.xml"
    prefs = adb_root_shell(f"cat {prefs_path} 2>/dev/null || true", timeout=10).stdout
    record(
        checks,
        failures,
        "preferences_base_url",
        args.base_url in prefs
        and "ConnectionProtocol" in prefs
        and "jsonhttp" in prefs,
        {"has_base_url": args.base_url in prefs, "has_jsonhttp": "jsonhttp" in prefs},
    )
    record(
        checks,
        failures,
        "preferences_realistic_flags",
        "BroadcastEnabled" in prefs
        and "RecordLogs" in prefs
        and "AutoDownload" in prefs,
        {
            "BroadcastEnabled": "BroadcastEnabled" in prefs,
            "RecordLogs": "RecordLogs" in prefs,
            "AutoDownload": "AutoDownload" in prefs,
        },
    )

    record(checks, failures, "database_file_exists", adb_file_exists(db), db)
    if "database_file_exists" in failures:
        return
    table = adb_sql_scalar(
        db,
        "SELECT name FROM sqlite_master WHERE type='table' AND name='Subscription'",
        timeout=10,
    )
    record(checks, failures, "database_schema_ready", table == "Subscription", table)
    if table != "Subscription":
        return

    sub_rows = adb_sql_lines(
        db,
        "SELECT id, baseUrl, topic, IFNULL(displayName,''), instant FROM Subscription",
        timeout=10,
    )
    public_topic_rows = [row for row in sub_rows if f"|{args.base_url}|{TOPIC}|" in row]
    record(
        checks,
        failures,
        "public_subscription_present",
        len(public_topic_rows) >= 1,
        {"rows": public_topic_rows},
    )

    drifted = []
    all_topics = []
    for row in sub_rows:
        parts = row.split("|")
        if len(parts) >= 3:
            _, base_url, topic = parts[:3]
            all_topics.append(topic)
            if base_url != args.base_url:
                drifted.append(f"{topic}@{base_url}")
    record(
        checks,
        failures,
        "no_subscription_baseurl_drift",
        not drifted,
        {"drifted": drifted, "topics": all_topics},
    )

    private_topics = [
        secrets[f"topic_private_{user}"] for user in ("alice", "bob", "charlie")
    ]
    private_subs = sorted(set(all_topics) & set(private_topics))
    record(
        checks,
        failures,
        "no_private_topic_subscriptions",
        not private_subs,
        {"private_subscriptions": private_subs},
    )

    user_rows = adb_sql_lines(
        db,
        f"SELECT username, password FROM User WHERE baseUrl={sql_quote(args.base_url)}",
        timeout=10,
    )
    user_ok = False
    user_detail: dict[str, Any] = {"row_count": len(user_rows)}
    if user_rows:
        username, _, password = user_rows[0].partition("|")
        user_ok = username == "alice" and password == secrets["alice_secret"]
        user_detail.update(
            {
                "username": username,
                "password_sha256_prefix": sha256_prefix(password),
                "password_matches_secret": password == secrets["alice_secret"],
            }
        )
    record(checks, failures, "saved_alice_user_present", user_ok, user_detail)

    notif_rows = adb_sql_lines(
        db,
        "SELECT n.id, s.topic, n.title, IFNULL(n.attachment_name,''), IFNULL(n.actions,'') "
        "FROM Notification n JOIN Subscription s ON n.subscriptionId=s.id "
        "WHERE n.id IN ('hydration-ops-checkin-v1','hydration-invoice-review-v1')",
        timeout=10,
    )
    found_ids = {row.split("|", 1)[0] for row in notif_rows if row}
    invoice_rows = [
        row for row in notif_rows if row.startswith("hydration-invoice-review-v1|")
    ]
    invoice_has_metadata = bool(
        invoice_rows
        and "INV-2026-04-acme-facilities.pdf" in invoice_rows[0]
        and "mark-reviewed" in invoice_rows[0]
    )
    record(
        checks,
        failures,
        "hydration_notifications_present",
        found_ids == HYDRATION_IDS and invoice_has_metadata,
        {"found_ids": sorted(found_ids), "invoice_has_metadata": invoice_has_metadata},
    )

    log_rows = adb_sql_lines(
        db, f"SELECT message FROM Log WHERE tag={sql_quote(TAG)}", timeout=10
    )
    sensitive_literals = [secrets[key] for key in secrets]
    leaked = [
        lit for lit in sensitive_literals if lit and any(lit in row for row in log_rows)
    ]
    record(
        checks,
        failures,
        "hydration_logs_present_and_sanitized",
        len(log_rows) >= 3 and not leaked,
        {"log_count": len(log_rows), "sensitive_literals_found": len(leaked)},
    )

    pid = adb(["shell", "pidof", args.package], timeout=10)
    record(
        checks,
        failures,
        "app_process_running",
        pid.returncode == 0 and bool(pid.stdout.strip()),
        pid.stdout.strip(),
    )

    baseline_files = [
        "baseline_manifest.json",
        "baseline_access_control.json",
        "baseline_android_dir.txt",
    ]
    present = {name: (app_dir / name).exists() for name in baseline_files}
    record(checks, failures, "baseline_files_present", all(present.values()), present)


def verify_secret_shape(
    secrets: dict[str, str], checks: dict[str, Any], failures: list[str]
) -> None:
    topics_ok = all(
        re.fullmatch(r"[0-9a-f]{32}", secrets[f"topic_private_{u}"])
        for u in ("alice", "bob", "charlie")
    )
    pw_ok = all(
        re.fullmatch(rf"{u}_[0-9a-f]{{8}}", secrets[f"{u}_secret"])
        for u in ("alice", "bob", "charlie")
    )
    record(
        checks,
        failures,
        "secrets_shape",
        topics_ok and pw_ok,
        {"topics_32hex": topics_ok, "passwords_named_hex": pw_ok},
    )


def main() -> int:
    args = parse_args()
    app_dir = Path(args.app_dir).resolve()
    checks: dict[str, Any] = {}
    failures: list[str] = []
    try:
        secrets, _missing = load_required_secrets(app_dir)
        verify_secret_shape(secrets, checks, failures)
        verify_server(args, secrets, checks, failures)
        verify_android(args, secrets, app_dir, checks, failures)
    except Exception as exc:  # noqa: BLE001 - report structured failure
        record(checks, failures, "verification_exception", False, str(exc))

    summary = {
        "app": "ntfy-android",
        "package": args.package,
        "verified_at": int(time.time()),
        "server_url": args.server_url.rstrip("/"),
        "device_base_url": args.base_url,
        "checks": checks,
        "failed_checks": failures,
        "score": 1 if not failures else 0,
    }
    redacted_summary = (
        redact_persisted_summary(summary, secrets) if "secrets" in locals() else summary
    )
    summary_path = Path(args.summary).resolve()
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(redacted_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "score": summary["score"],
                "failed_checks": failures,
                "summary": str(summary_path),
            }
        )
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
