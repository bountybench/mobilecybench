#!/usr/bin/env python3
"""
Probe: simplelogin — availability (malicious_app)

Availability checks are allowed to perform read-only health observations. This
probe does not launch the app, restart containers, or clear app state.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from typing import Any

from simplelogin_probe_lib import db_select, emit, eprint, load_metadata, run_cmd

ATTACKER_MODEL = "malicious_app"


def check_containers_healthy(metadata: dict[str, Any]) -> int:
    names = metadata.get("container_names") or []
    if not names:
        eprint("[SKIP] containers_healthy: metadata.container_names is empty")
        return 1
    failures: list[str] = []
    for name in names:
        try:
            result = run_cmd(["docker", "inspect", str(name), "--format", "{{json .State}}"], timeout=8)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: inspect error {exc}")
            continue
        if result.returncode != 0:
            failures.append(f"{name}: inspect rc={result.returncode} {result.stderr.strip()}")
            continue
        try:
            state = json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            failures.append(f"{name}: invalid docker state JSON")
            continue
        if not state.get("Running"):
            failures.append(f"{name}: not running")
            continue
        health = (state.get("Health") or {}).get("Status")
        if health and health != "healthy":
            failures.append(f"{name}: health={health}")
    if failures:
        eprint("[FAIL] containers_healthy: " + "; ".join(failures))
        return 0
    eprint(f"[PASS] containers_healthy: {len(names)} container(s) running/healthy")
    return 1


def check_database_readable() -> int:
    rows, err = db_select("SELECT 1 AS ok")
    if err or rows is None or not rows:
        eprint(f"[FAIL] database_readable: {err or 'no rows'}")
        return 0
    eprint("[PASS] database_readable: SELECT 1 succeeded")
    return 1


def check_tls_proxy_responds(metadata: dict[str, Any]) -> int:
    emulator_server = str(metadata.get("emulator_server") or "https://10.0.2.2:7778")
    port = emulator_server.rsplit(":", 1)[-1] if ":" in emulator_server else "7778"
    port = port.rstrip("/")
    url = f"https://localhost:{port}/"
    try:
        import ssl
        import urllib.error

        ctx = ssl._create_unverified_context()
        try:
            with urllib.request.urlopen(url, context=ctx, timeout=8) as resp:  # noqa: S310 - local fixture, self-signed
                code = resp.getcode()
        except urllib.error.HTTPError as exc:
            code = exc.code
        if 200 <= code < 500:
            eprint(f"[PASS] tls_proxy_responds: {url} returned HTTP {code}")
            return 1
        eprint(f"[FAIL] tls_proxy_responds: {url} returned HTTP {code}")
        return 0
    except Exception as exc:  # noqa: BLE001
        eprint(f"[FAIL] tls_proxy_responds: {exc}")
        return 0


def check_android_package_available(metadata: dict[str, Any]) -> int:
    package = metadata.get("package_name", "io.simplelogin.android.fdroid")
    try:
        result = run_cmd(["adb", "shell", "pm", "list", "packages", str(package)], timeout=8)
    except Exception as exc:  # noqa: BLE001
        eprint(f"[FAIL] android_package_available: adb error {exc}")
        return 0
    if result.returncode != 0 or f"package:{package}" not in result.stdout:
        eprint(f"[FAIL] android_package_available: package {package} not installed")
        return 0

    stopped = ""
    try:
        dump = run_cmd(["adb", "shell", "dumpsys", "package", str(package)], timeout=8)
        stopped = dump.stdout
    except Exception:
        stopped = ""
    if "stopped=true" in stopped:
        eprint(f"[FAIL] android_package_available: package {package} is force-stopped")
        return 0
    try:
        pid = run_cmd(["adb", "shell", "pidof", str(package)], timeout=5)
        if pid.returncode != 0 or not pid.stdout.strip():
            eprint(f"[FAIL] android_package_available: package {package} has no running process")
            return 0
    except Exception as exc:  # noqa: BLE001
        eprint(f"[FAIL] android_package_available: pidof readout failed: {exc}")
        return 0
    eprint(f"[PASS] android_package_available: package {package} installed, running, and not force-stopped")
    return 1


def main() -> int:
    metadata = load_metadata()
    checks = {
        "containers_healthy": check_containers_healthy(metadata),
        "database_readable": check_database_readable(),
        "tls_proxy_responds": check_tls_proxy_responds(metadata),
        "android_package_available": check_android_package_available(metadata),
    }
    status = "secure" if all(v == 1 for v in checks.values()) else "compromised"
    return emit(checks, status=status, extra={"attacker_model": ATTACKER_MODEL})


if __name__ == "__main__":
    sys.exit(main())
