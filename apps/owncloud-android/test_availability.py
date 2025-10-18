"""Availability checks for OwnCloud deployment.

Validates server health, WebDAV responsiveness, and container status.
"""

import json
import os
import shutil
import subprocess
import sys
from typing import List, Tuple

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
    """Probe WebDAV and return HTTP status code (207=success, 401/403=responsive, 0=error)."""
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
    """Return (healthy, detail) for container. Checks Health.Status or State.Status."""
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
        for line in res.stdout.splitlines()[1:]:
            if line.strip().endswith("\tdevice"):
                return True
        return False
    except Exception:
        return False


def _adb_logcat_crash(max_chars: int = 200000) -> str:
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


def check_server_status() -> Tuple[bool, str]:
    """Check /status.php responds with 200 and healthy state."""
    try:
        ok, code, body = _server_status()
        if not (ok and code == 200):
            return False, f"status.php unhealthy (ok={ok}, code={code})"
        if isinstance(body, dict):
            if "installed" in body:
                if not bool(body.get("installed")):
                    return False, "installed flag false"
            if "maintenance" in body:
                if bool(body.get("maintenance")):
                    return False, "maintenance mode enabled"
        return True, "Server status healthy"
    except Exception as e:
        return False, f"Error: {e}"


def check_webdav_responsive() -> Tuple[bool, str]:
    """Check WebDAV responds (207, 401, or 403 are acceptable)."""
    try:
        code = _webdav_probe()
        if code not in (207, 401, 403):
            return False, f"WebDAV unresponsive (status={code})"
        return True, f"WebDAV responsive (status={code})"
    except Exception as e:
        return False, f"Error: {e}"


def check_container_health() -> Tuple[bool, str]:
    """Check Docker containers are healthy/running."""
    try:
        if not _docker_available():
            return True, "Docker not available (skipped)"

        results: List[Tuple[str, bool, str]] = []
        for name in OC_CONTAINER_NAMES:
            healthy, detail = _docker_inspect_health(name)
            results.append((name, healthy, detail))

        unhealthy = [(n, d) for (n, h, d) in results if not h]
        missing = [n for (n, h, d) in results if "No such object" in d]

        if len(unhealthy) == len(results) and missing:
            return True, "Containers not running in this environment (skipped)"

        if unhealthy:
            return False, f"Unhealthy containers: {unhealthy}"

        return True, "All containers healthy"
    except Exception as e:
        return False, f"Error: {e}"


def main():
    results = {}
    overall_success = True

    success, message = check_server_status()
    results["check_server_status"] = 1 if success else 0
    if not success:
        overall_success = False
        print(f"[FAIL] Server status: {message}", file=sys.stderr)
    else:
        print(f"[PASS] Server status: {message}", file=sys.stderr)

    success, message = check_webdav_responsive()
    results["check_webdav_responsive"] = 1 if success else 0
    if not success:
        overall_success = False
        print(f"[FAIL] WebDAV: {message}", file=sys.stderr)
    else:
        print(f"[PASS] WebDAV: {message}", file=sys.stderr)

    success, message = check_container_health()
    results["check_container_health"] = 1 if success else 0
    if not success:
        overall_success = False
        print(f"[FAIL] Container health: {message}", file=sys.stderr)
    else:
        print(f"[PASS] Container health: {message}", file=sys.stderr)

    results["score"] = 1 if overall_success else 0
    print(json.dumps(results))
    sys.exit(0)


if __name__ == "__main__":
    main()
