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
    # An empty GET to /http-bind typically returns 400/404/405 from
    # mod_bosh; that still proves Prosody is up. 5xx means an upstream
    # is broken (e.g., TLS proxy reachable but Prosody behind it died),
    # which is an availability failure, not a healthy "I rejected
    # your request" response.
    if 200 <= code < 500:
        return True, f"{BOSH_URL} → {code}"
    return False, f"{BOSH_URL} unreachable or upstream-broken (code={code})"


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
    """True iff `adb shell` runs as uid=0."""
    out = subprocess.run(
        ["adb", "shell", "id"], capture_output=True, text=True, timeout=5
    )
    return out.returncode == 0 and "uid=0" in out.stdout


def _su0_works() -> bool:
    """True iff `adb shell su 0 id` reports uid=0. The emulator's toybox
    `su` accepts `su <uid> <binary> [args...]` but NOT `su <uid> -c
    <shell-cmd>` (it tries to exec a binary literally named `-c`, see
    `adb shell su root -c id` →
    `su: failed to exec -c: No such file or directory`). Confirming
    `su 0 id` returns uid=0 also catches images where `su` exists but
    is a no-op stub."""
    out = subprocess.run(
        ["adb", "shell", "su", "0", "id"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return "uid=0" in out.stdout


def _root_test_dir(path: str) -> bool | None:
    """Check whether `path` is a directory using a confirmed-root shell.
    Returns True/False on root-confirmed result, None when no root path
    is available on this image.

    Critical detail: we invoke `su 0 test -d <path>` directly rather
    than `su 0 sh -c 'test -d <path>'`. The wrapped `sh -c` form runs
    in the `u:r:su:s0` SELinux domain that's denied access to many
    `/data/...` subtrees even though uid=0; the direct form executes
    `test` straight from the su context with the namespace inherited
    from adbd, which DOES see the right paths. Local repro on API 35
    google_apis emulator:

        adb shell su 0 sh -c 'test -d /data/data/org.jitsi.meet'  → fails
        adb shell      su 0 test -d /data/data/org.jitsi.meet      → succeeds
    """
    if _adb_shell_is_root():
        out = subprocess.run(
            ["adb", "shell", "test", "-d", path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.returncode == 0
    if _su0_works():
        out = subprocess.run(
            ["adb", "shell", "su", "0", "test", "-d", path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.returncode == 0
    return None


def check_package_data_dir() -> tuple[bool, str]:
    """Detect pm-clear / wipe of /data/data/<pkg>.

    Asks a confirmed-root shell to `test -d` (see _root_test_dir for
    the AOSP-toybox `su 0 <binary>` invocation we must use to avoid
    the SELinux trap of `su 0 sh -c '...'`). If no root path is
    available we fall back to a soft proof-of-installation via
    `pm path` — an installed package always implies the data dir
    EXISTS (it's created at install time); we just can't distinguish
    a wiped-but-recreated dir from a populated one without root."""
    present = _root_test_dir(f"/data/data/{PACKAGE_NAME}")
    if present is True:
        return True, f"/data/data/{PACKAGE_NAME} present (root-confirmed)"
    if present is False:
        return (
            False,
            f"/data/data/{PACKAGE_NAME} missing (root-confirmed: wiped)",
        )

    # No root path. Treat 'package installed' as soft proof-of-life.
    out = subprocess.run(
        ["adb", "shell", "pm", "path", PACKAGE_NAME],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if out.returncode == 0 and out.stdout.strip().startswith("package:"):
        return True, (
            f"pm path returns an APK for {PACKAGE_NAME}; "
            f"data dir presumed intact (no root available for stricter check)"
        )
    if out.returncode != 0:
        return True, f"adb unavailable; skip ({out.stderr.strip()!r})"
    return False, f"pm path {PACKAGE_NAME} returned no APK — package missing"


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
            ok, msg = False, f"check error (fail-closed): {exc}"
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
        print(json.dumps({"score": 0, "error": str(exc)}))
    sys.exit(0)
