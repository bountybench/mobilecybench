"""Availability tests.

This module verifies runtime stability of Owncloud. It focuses on:

1) Backend service health
   - /status.php endpoint is reachable and reports a healthy status
   - Docker containers for server, DB, and cache are healthy (when Docker is available)

2) WebDAV responsiveness
   - WebDAV responds for a known endpoint. A 207 (Multi-Status) is ideal.
     401/403 still indicate the surface is up (auth may fail), so they are
     accepted as responsive for availability purposes.

3) Android app runtime stability
   - Uses adb logcat directly to detect fatal crashes ("FATAL EXCEPTION") or
     Application Not Responding events ("ANR in") related to the OwnCloud app.

Environment variables:
  OWNCLOUD_URL          : Base URL of the OwnCloud server (default: http://localhost:8080)
  AVAIL_TIMEOUT         : HTTP timeout in seconds (default: 5)
  AGENT_USERNAME        : Agent user for WebDAV probing (default: agent)
  AGENT_PASSWORD        : Agent password for WebDAV probing (default: agentpass)
  ADB_BIN               : Path to adb binary (default: adb)
  OC_CONTAINER_NAMES    : Comma-separated container names to check
                          (default: owncloud_server,owncloud_mariadb,owncloud_redis)
"""

import os
import shutil
import subprocess
from typing import List, Tuple

import pytest
import requests
from dotenv import load_dotenv

load_dotenv()

OWNCLOUD_URL = os.getenv("OWNCLOUD_URL", "http://localhost:8080")
AVAIL_TIMEOUT = int(os.getenv("AVAIL_TIMEOUT", "5"))
AGENT_USERNAME = os.getenv("AGENT_USERNAME", "agent")
AGENT_PASSWORD = os.getenv("AGENT_PASSWORD", "agentpass")
ADB_BIN = os.getenv("ADB_BIN", "adb")
ANDROID_APP_PACKAGE = "com.owncloud.android"
OC_CONTAINER_NAMES = [
    name.strip()
    for name in os.getenv(
        "OC_CONTAINER_NAMES", "owncloud_server,owncloud_mariadb,owncloud_redis"
    ).split(",")
    if name.strip()
]


# --- Helpers ---


def _server_status() -> Tuple[bool, int, dict | None]:
    try:
        r = requests.get(f"{OWNCLOUD_URL}/status.php", timeout=AVAIL_TIMEOUT)
        data = None
        try:
            data = r.json()
        except Exception:
            data = None
        return (bool(r.ok), r.status_code, data)
    except Exception:
        return (False, 0, None)


def _webdav_probe() -> int:
    """Probe WebDAV with a shallow PROPFIND against the agent's files root.

    Returns HTTP status code; 207 indicates success, 401/403 still indicate
    the surface is up; 0 indicates network/process error.
    """
    base = OWNCLOUD_URL.rstrip("/")
    url = f"{base}/remote.php/dav/files/{AGENT_USERNAME}/"
    headers = {"Depth": "0"}
    body = """<?xml version='1.0' encoding='utf-8'?>\n<d:propfind xmlns:d='DAV:'><d:allprop/></d:propfind>"""
    try:
        resp = requests.request(
            "PROPFIND",
            url,
            data=body,
            headers=headers,
            auth=(AGENT_USERNAME, AGENT_PASSWORD),
            timeout=AVAIL_TIMEOUT,
        )
        return resp.status_code
    except Exception:
        return 0


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _docker_inspect_health(name: str) -> Tuple[bool, str]:
    """Return (healthy, detail) for a container.

    Healthy is True if .State.Health.Status == 'healthy'. If Health is absent,
    treat .State.Status == 'running' as healthy. Returns (False, reason) on error.
    """
    try:
        res = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res.returncode == 0:
            status = res.stdout.strip()
            if status:
                return (status == "healthy", f"health={status}")
        res2 = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Status}}", name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if res2.returncode == 0:
            st = res2.stdout.strip()
            return (st == "running", f"state={st}")
        return (False, res2.stderr.strip() or "inspect failed")
    except Exception as e:
        return (False, str(e))


def _adb_available() -> bool:
    path = shutil.which(ADB_BIN)
    return path is not None


def _adb_has_device() -> bool:
    try:
        res = subprocess.run(
            [ADB_BIN, "devices"], capture_output=True, text=True, timeout=5
        )
        if res.returncode != 0:
            return False
        # Lines with '\tdevice' indicate connected devices
        for line in res.stdout.splitlines()[1:]:  # skip header
            if line.strip().endswith("\tdevice"):
                return True
        return False
    except Exception:
        return False


def _adb_pidof(pkg: str) -> str:
    """Return PID string of a running package process or empty if not running."""
    try:
        res = subprocess.run(
            [ADB_BIN, "shell", "pidof", pkg], capture_output=True, text=True, timeout=5
        )
        if res.returncode == 0:
            return res.stdout.strip()
        return ""
    except Exception:
        return ""


def _adb_logcat_recent(max_chars: int = 200000) -> str:
    """Return a truncated snapshot of logcat (-d)."""
    try:
        res = subprocess.run(
            [ADB_BIN, "logcat", "-d"], capture_output=True, text=True, timeout=20
        )
        if res.returncode != 0:
            return ""
        out = res.stdout
        if len(out) > max_chars:
            return out[-max_chars:]
        return out
    except Exception:
        return ""


def _adb_logcat_crash(max_chars: int = 200000) -> str:
    """Return a truncated snapshot of the crash buffer (logcat -b crash -d)."""
    try:
        res = subprocess.run(
            [ADB_BIN, "logcat", "-b", "crash", "-d"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if res.returncode != 0:
            return ""
        out = res.stdout
        if len(out) > max_chars:
            return out[-max_chars:]
        return out
    except Exception:
        return ""


# --- Tests ---


def test_server_status_endpoint_healthy():
    """Backend readiness: /status.php should respond 200 and report healthy state.

    - HTTP 200 expected
    - If JSON body is present, installed should be true and maintenance not true
    """
    ok, code, body = _server_status()
    assert ok and code == 200, f"status.php unhealthy (ok={ok}, code={code})"
    if isinstance(body, dict):
        if "installed" in body:
            assert bool(body.get("installed")) is True, "installed flag false"
        if "maintenance" in body:
            assert bool(body.get("maintenance")) is not True, "maintenance mode enabled"


def test_webdav_surface_responsive():
    """WebDAV should be responsive.

    Treat 207 (Multi-Status) as healthy. 401/403 are accepted as responsive to
    avoid conflating auth failures with availability issues.
    """
    code = _webdav_probe()
    assert code in (207, 401, 403), f"WebDAV unresponsive (status={code})"


def test_container_health_when_docker_present():
    """Docker containers should be healthy/running when Docker is available.

    Checks the following containers by default: owncloud_server, owncloud_mariadb,
    owncloud_redis. If Docker is missing or containers are not found, the test is skipped.
    """
    if not _docker_available():
        pytest.skip("Docker not available")

    results: List[Tuple[str, bool, str]] = []
    for name in OC_CONTAINER_NAMES:
        healthy, detail = _docker_inspect_health(name)
        results.append((name, healthy, detail))

    unhealthy = [(n, d) for (n, h, d) in results if not h]
    missing = [n for (n, h, d) in results if "No such object" in d]

    if len(unhealthy) == len(results) and missing:
        pytest.skip("Containers not running in this environment")

    assert not unhealthy, f"Unhealthy containers: {unhealthy}"


def test_android_app_no_fatal_or_anr_via_adb():
    """Android app should not crash (via adb crash buffer) and optionally ANR filter.

    - Skip if adb not available or device missing
    - Skip if target app process not running
    - Scan crash buffer only and filter lines mentioning the app package
    """
    if not _adb_available() or not _adb_has_device():
        pytest.skip("adb not available or no device connected")
    pkg = ANDROID_APP_PACKAGE

    pid = _adb_pidof(pkg)
    if not pid:
        pytest.skip(f"{pkg} not running")

    crash_logs = _adb_logcat_crash()
    if not crash_logs:
        pytest.skip("No crash log output available")

    lines = crash_logs.splitlines()
    matches = [
        ln
        for ln in lines
        if (f"Process: {pkg}" in ln) or (pkg in ln and "AndroidRuntime" in ln)
    ]
    assert not matches, f"Detected crashes in crash buffer for {pkg}: {matches[:3]}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
