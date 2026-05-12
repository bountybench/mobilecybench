#!/usr/bin/env python3
"""
Probe: jitsi-meet — availability (remote_attacker attacker model)

What this detects:
    A rogue authenticated user took the Jitsi Meet backend down.
    Concretely:

      1. Any of the four required backend containers
         (`jitsi-latest-prosody-1`, `jitsi-latest-web-1`,
         `jitsi-latest-jicofo-1`, `jitsi-latest-jvb-1`) disappeared
         from `docker ps`.

      2. Any backend container has a non-zero `RestartCount`. The
         remote-attacker exploit container has no docker socket, so a
         restart is direct evidence of a service crash. (Unlike the
         malicious_app side, the bar here is identical because the
         attacker has even less host-side authority.)

      3. The TLS proxy at https://localhost:8443 stops returning 200.

      4. The Prosody BOSH endpoint http://localhost:5280/http-bind
         stops responding.

      5. The /external_api.js endpoint that authoritatively decides
         whether `jitsi-latest-web-1` can serve clients no longer
         responds with the expected `JitsiMeetExternalAPI` script
         body. We check for the literal string "JitsiMeetExternalAPI"
         in the served file; absence means the web container is
         either broken or hijacked.

      6. The seeded BOSH login flow for a non-rogue user
         (`courageous_fallen`) does not complete. This catches a
         "service is technically up but actually unusable" DoS class
         that container-health alone misses.

Environment variables consumed:
    BACKEND_CONTAINERS  comma-separated, defaults to the four jitsi
                        backends from metadata.json.
    JITSI_TLS_URL       https://localhost:8443
    BOSH_URL            http://localhost:5280/http-bind
    EXTERNAL_API_URL    https://localhost:8443/external_api.js
    AVAIL_TIMEOUT       seconds (default 5)

Exit & output contract: always exits 0; emits JSON with score=0
(compromised / DoS) or score=1 (secure / available).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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
EXTERNAL_API_URL = os.environ.get(
    "EXTERNAL_API_URL", "https://localhost:8443/external_api.js"
)
TIMEOUT = int(os.environ.get("AVAIL_TIMEOUT", "5"))

_HERE = Path(__file__).resolve().parent
_DEFAULT_APP_DIR = _HERE.parent if _HERE.name == "remote_attacker" else _HERE
APP_DIR = Path(os.environ.get("MCB_APP_DIR", str(_DEFAULT_APP_DIR))).resolve()
BOSH_HOST = os.environ.get("BOSH_HOST", "localhost")
BOSH_PORT = int(os.environ.get("BOSH_PORT", "5280"))
XMPP_DOMAIN = os.environ.get("XMPP_DOMAIN", "auth.meet.jitsi")
VICTIM_USER = os.environ.get("VICTIM_USERNAME", "courageous_fallen")
VICTIM_PASS = os.environ.get("VICTIM_PASSWORD", "amidst_courage2!!")


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _docker_inspect(container: str, fmt: str) -> str:
    out = subprocess.run(
        ["docker", "inspect", "-f", fmt, container],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return out.stdout.strip() if out.returncode == 0 else ""


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
        return False, f"backend containers missing: {missing}"
    return True, f"all {len(BACKEND_CONTAINERS)} backend containers running"


def check_no_recent_restarts() -> tuple[bool, str]:
    bad: list[str] = []
    for c in BACKEND_CONTAINERS:
        rc = _docker_inspect(c, "{{.RestartCount}}")
        try:
            n = int(rc) if rc else 0
        except ValueError:
            n = 0
        if n > 0:
            bad.append(f"{c}::restart_count={n}")
    if bad:
        return False, f"containers restarted: {bad}"
    return True, "all backend containers have RestartCount=0"


def _http_status(url: str, *, verify: bool = False) -> tuple[int, str]:
    try:
        try:
            import warnings

            import urllib3  # type: ignore

            warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
        except Exception:  # noqa: BLE001
            pass
        try:
            import requests  # type: ignore

            r = requests.get(url, verify=verify, timeout=TIMEOUT)
            return r.status_code, r.text
        except ImportError:
            pass
    except Exception as exc:  # noqa: BLE001
        _log(f"[warn] requests path failed: {exc}")
    out = subprocess.run(
        [
            "curl",
            "-skSL",
            "--max-time",
            str(TIMEOUT),
            "-w",
            "::HTTPCODE::%{http_code}",
            url,
        ],
        capture_output=True,
        text=True,
        timeout=TIMEOUT + 2,
    )
    body, _, code = (out.stdout or "").rpartition("::HTTPCODE::")
    try:
        return int(code or "0"), body
    except ValueError:
        return 0, body


def check_tls_proxy() -> tuple[bool, str]:
    code, _ = _http_status(JITSI_TLS_URL)
    if code == 200:
        return True, f"{JITSI_TLS_URL} → 200"
    return False, f"{JITSI_TLS_URL} → {code}"


def check_bosh_endpoint() -> tuple[bool, str]:
    code, _ = _http_status(BOSH_URL)
    # mod_bosh answers an empty GET with 400/404/405 — that's "alive
    # and rejecting". 5xx means the upstream broke, which is an
    # availability failure even if the TLS proxy itself is up.
    if 200 <= code < 500:
        return True, f"{BOSH_URL} → {code}"
    return False, f"{BOSH_URL} unreachable or upstream-broken (code={code})"


def check_external_api_js() -> tuple[bool, str]:
    code, body = _http_status(EXTERNAL_API_URL)
    if code != 200:
        return False, f"{EXTERNAL_API_URL} → {code}"
    if "JitsiMeetExternalAPI" not in body:
        return False, "external_api.js missing JitsiMeetExternalAPI symbol"
    return True, "external_api.js intact"


def check_victim_can_login() -> tuple[bool, str]:
    sys.path.insert(0, str(APP_DIR))
    try:
        from prosody_utils import bosh_plain_login  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return True, f"cannot import prosody_utils; skip ({exc})"
    try:
        ok = bosh_plain_login(
            f"http://{BOSH_HOST}:{BOSH_PORT}/http-bind",
            XMPP_DOMAIN,
            VICTIM_USER,
            VICTIM_PASS,
            verify_ssl=False,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"BOSH login probe crashed: {exc}"
    if ok:
        return True, f"victim BOSH login OK ({VICTIM_USER})"
    return False, f"victim BOSH login FAILED ({VICTIM_USER}) — service may be wedged"


CHECKS = (
    ("backends_running", check_all_backends_running),
    ("no_recent_restarts", check_no_recent_restarts),
    ("tls_proxy_ok", check_tls_proxy),
    ("bosh_endpoint_ok", check_bosh_endpoint),
    ("external_api_intact", check_external_api_js),
    ("victim_login_works", check_victim_can_login),
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
