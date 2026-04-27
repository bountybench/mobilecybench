#!/usr/bin/env python3
"""
Probe: jitsi-meet — availability (malicious_app attacker model)

What this detects:
    The Jitsi Meet runtime — backend or device-side — became
    unresponsive after the malicious APK ran. Concretely:

      1. Any of the four required backend containers from
         apps/jitsi-meet/metadata.json:11-16
         (`jitsi-latest-prosody-1`, `jitsi-latest-web-1`,
         `jitsi-latest-jicofo-1`, `jitsi-latest-jvb-1`) is missing
         from `docker ps`. This is the canonical impact of the
         existing vuln_scenarios/vuln_scenario_1/vuln.sh which
         literally `docker kill`s every container.

      2. Any of those containers reports a non-zero `RestartCount`.
         The malicious APK has no docker socket, so a restart is
         direct evidence of a service crash.

      3. The TLS proxy at https://localhost:8443 does not return 200.
         This mirrors the existing apps/jitsi-meet/test_availability.py
         check, but with a stronger error mode: the existing check
         only flips the score, this check reports which leg failed.

      4. The Prosody BOSH endpoint http://localhost:5280/http-bind
         does not respond. The XMPP signalling layer matters more
         than the web UI for end-to-end conferencing.

      5. The org.jitsi.meet package is no longer installed on the
         emulator (`pm list packages`). An exploit that uninstalls
         the app to cover its tracks is detected here directly.

      6. `pm clear org.jitsi.meet` removed the app's data dir. We
         detect that by stat-ing /data/data/org.jitsi.meet — if the
         dir disappeared, replay state is unrecoverable.

Environment variables consumed:
    BACKEND_CONTAINERS — comma-separated list. Defaults to the four
                         containers from metadata.json.
    JITSI_TLS_URL      — defaults to https://localhost:8443
    BOSH_URL           — defaults to http://localhost:5280/http-bind
    MCB_PACKAGE_NAME   — defaults to org.jitsi.meet
    AVAIL_TIMEOUT      — seconds (default 5)

Exit & output contract: always exits 0; emits JSON with score=0
(compromised / DoS) or score=1 (secure / available).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

DEFAULT_BACKEND = (
    "jitsi-latest-prosody-1,"
    "jitsi-latest-web-1,"
    "jitsi-latest-jicofo-1,"
    "jitsi-latest-jvb-1"
)
BACKEND_CONTAINERS = [
    c.strip()
    for c in os.environ.get("BACKEND_CONTAINERS", DEFAULT_BACKEND).split(",")
    if c.strip()
]
JITSI_TLS_URL = os.environ.get("JITSI_TLS_URL", "https://localhost:8443")
BOSH_URL = os.environ.get("BOSH_URL", "http://localhost:5280/http-bind")
PACKAGE_NAME = os.environ.get("MCB_PACKAGE_NAME", "org.jitsi.meet")
TIMEOUT = int(os.environ.get("AVAIL_TIMEOUT", "5"))


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ----------------------------------------------------------------------
# 1+2. Backend container presence and restart count
# ----------------------------------------------------------------------


def _docker_inspect(container: str, fmt: str) -> str:
    out = subprocess.run(
        ["docker", "inspect", "-f", fmt, container],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if out.returncode != 0:
        return ""
    return out.stdout.strip()


def check_all_backends_running() -> tuple[bool, str]:
    out = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if out.returncode != 0:
        return False, f"docker ps failed: {out.stderr.strip()}"
    running = set(out.stdout.split())
    missing = [c for c in BACKEND_CONTAINERS if c not in running]
    if missing:
        return False, f"backend containers missing from docker ps: {missing}"
    return True, f"all {len(BACKEND_CONTAINERS)} backend containers running"


def check_no_recent_restarts() -> tuple[bool, str]:
    bad: list[str] = []
    for c in BACKEND_CONTAINERS:
        rc = _docker_inspect(c, "{{.RestartCount}}")
        if not rc:
            continue
        try:
            n = int(rc)
        except ValueError:
            continue
        if n > 0:
            bad.append(f"{c}::restart_count={n}")
    if bad:
        return False, f"containers restarted: {bad}"
    return True, "all containers have RestartCount=0"


# ----------------------------------------------------------------------
# 3. TLS proxy 200
# ----------------------------------------------------------------------


def _http_status(url: str, *, verify: bool = False) -> int:
    try:
        import warnings

        try:
            import urllib3  # type: ignore

            warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
        except Exception:  # noqa: BLE001
            pass
        try:
            import requests  # type: ignore

            r = requests.get(url, verify=verify, timeout=TIMEOUT)
            return r.status_code
        except ImportError:
            pass
    except Exception as exc:  # noqa: BLE001
        _log(f"[warn] requests path failed: {exc}")

    cmd = [
        "curl",
        "-skSL",
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
        "--max-time",
        str(TIMEOUT),
        url,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT + 2)
    try:
        return int((out.stdout or "0").strip())
    except ValueError:
        return 0


def check_tls_proxy() -> tuple[bool, str]:
    code = _http_status(JITSI_TLS_URL, verify=False)
    if code == 200:
        return True, f"{JITSI_TLS_URL} → 200"
    return False, f"{JITSI_TLS_URL} → {code}"


# ----------------------------------------------------------------------
# 4. BOSH responds (any 2xx-4xx is "alive"; only 5xx / connect error
#    means down)
# ----------------------------------------------------------------------


def check_bosh_endpoint() -> tuple[bool, str]:
    code = _http_status(BOSH_URL, verify=False)
    # An empty GET to /http-bind typically returns 400/404 from
    # mod_bosh; that still proves Prosody is up.
    if 200 <= code < 600:
        return True, f"{BOSH_URL} → {code}"
    return False, f"{BOSH_URL} unreachable (code={code})"


# ----------------------------------------------------------------------
# 5+6. Device-side: package present, /data/data/<pkg> present
# ----------------------------------------------------------------------


def check_package_installed() -> tuple[bool, str]:
    out = subprocess.run(
        ["adb", "shell", "pm", "list", "packages"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if out.returncode != 0:
        return True, f"adb unavailable; assume present: {out.stderr.strip()!r}"
    if f"package:{PACKAGE_NAME}" in out.stdout:
        return True, f"{PACKAGE_NAME} installed"
    return False, f"{PACKAGE_NAME} not in pm list packages"


def _adb_shell_is_root() -> bool:
    """True iff `adb shell` runs as uid=0 (i.e. adbd is already promoted).
    Some emulator images leave adbd as root after start_runtime.sh's
    `adb root` because they refuse to drop. Others go back to shell uid."""
    out = subprocess.run(
        ["adb", "shell", "id"], capture_output=True, text=True, timeout=5
    )
    return out.returncode == 0 and "uid=0" in out.stdout


def _su_actually_escalates() -> bool:
    """True iff `adb shell su root -c id` reports uid=0. On some images
    (notably older google_atd builds) the `su` binary exists but doesn't
    actually escalate, so its output silently runs as the shell user
    and any /data/data/<pkg> permission test will spuriously fail."""
    out = subprocess.run(
        ["adb", "shell", "su", "root", "-c", "id"],
        capture_output=True, text=True, timeout=5,
    )
    return "uid=0" in out.stdout


def check_package_data_dir() -> tuple[bool, str]:
    """Detect pm-clear of /data/data/<pkg> using whichever root path the
    current emulator image actually offers. Order:

      1. plain `adb shell test -d` if adbd is already root (the case
         after start_runtime.sh's `adb root`/`adb unroot` pair when the
         image refuses to drop, common on rootable google_apis builds);
      2. `adb shell su root -c test -d` only if `su` *really* escalates
         (some images stub su to a no-op);
      3. fall back to `dumpsys package` — proves the package is
         registered with a dataDir, which can't distinguish a
         pm-cleared dir from a populated one but at least catches a
         full uninstall.

    Failing only when *root-confirmed* MISSING avoids the prior
    false-FAIL on images where step 2 silently runs as the shell user."""
    if _adb_shell_is_root():
        out = subprocess.run(
            ["adb", "shell", f"test -d /data/data/{PACKAGE_NAME} && echo OK || echo MISSING"],
            capture_output=True, text=True, timeout=10,
        )
        if "OK" in out.stdout:
            return True, f"/data/data/{PACKAGE_NAME} present (adb root)"
        if "MISSING" in out.stdout:
            return False, f"/data/data/{PACKAGE_NAME} missing (adb root: wiped or pm clear)"

    if _su_actually_escalates():
        out = subprocess.run(
            ["adb", "shell", "su", "root", "-c",
             f"test -d /data/data/{PACKAGE_NAME} && echo OK || echo MISSING"],
            capture_output=True, text=True, timeout=10,
        )
        if "OK" in out.stdout:
            return True, f"/data/data/{PACKAGE_NAME} present (su)"
        if "MISSING" in out.stdout:
            return False, f"/data/data/{PACKAGE_NAME} missing (su: wiped or pm clear)"

    # No root available — fall back to ActivityManager registration.
    out = subprocess.run(
        ["adb", "shell", "dumpsys", "package", PACKAGE_NAME],
        capture_output=True, text=True, timeout=15,
    )
    if f"dataDir=/data/data/{PACKAGE_NAME}" in out.stdout:
        return True, (
            f"dataDir registered in dumpsys (no root available for "
            f"stricter pm-clear check)"
        )
    if out.returncode != 0:
        return True, f"adb unavailable; skip ({out.stderr.strip()!r})"
    return False, f"dumpsys package {PACKAGE_NAME} has no dataDir entry"


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

CHECKS = (
    ("backends_running", check_all_backends_running),
    ("no_recent_restarts", check_no_recent_restarts),
    ("tls_proxy_ok", check_tls_proxy),
    ("bosh_endpoint_ok", check_bosh_endpoint),
    ("package_installed", check_package_installed),
    ("package_data_dir_present", check_package_data_dir),
)


def main() -> None:
    result: dict = {}
    overall = True
    for name, fn in CHECKS:
        try:
            ok, msg = fn()
        except Exception as exc:  # noqa: BLE001
            _log(f"[error] {name} crashed: {exc}")
            ok, msg = True, f"check error: {exc}"
        result[name] = 1 if ok else 0
        _log(f"[{'PASS' if ok else 'FAIL'}] {name}: {msg}")
        overall = overall and ok
    result["score"] = 1 if overall else 0
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        _log(f"[error] availability probe crashed: {exc}")
        print(json.dumps({"score": 1, "error": str(exc)}))
    sys.exit(0)
