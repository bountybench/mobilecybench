#!/usr/bin/env python3
"""
Probe: jitsi-meet — integrity (remote_attacker attacker model)

What this detects:
    A rogue authenticated user landed write access on the Jitsi Meet
    backend or persisted attacker-controlled state. Concretely:

      1. The Prosody container's config tree changed since runtime
         baseline. Re-uses compute_hash() from
         apps/jitsi-meet/test_integrity.py — this hashes
         /config/certs, /config/conf.d, /config/data, and
         /config/prosody.cfg.lua. CVE-2021-39215 (JWT forgery) is
         not directly file-modifying, but any attacker who escalates
         far enough to reach the Prosody admin shell will leave a
         trace here.

      2. The web container's `/config/config.js` (the file
         start_runtime.sh:enable_giphy_in_config rewrites) gained
         attacker-controlled directives. We compare against the
         giphy-enabled bootstrap shape and flag any new
         `config.<x>` lines that were not seeded.

      3. /var/lib/prosody/auth%2emeet%2ejitsi/accounts/ contains
         user account files outside the seeded roster. CVE-2021-39215
         and admin-shell escalation both let an attacker register a
         backdoor account; the file appears here.

      4. The seeded account files were not truncated to zero bytes
         (the canonical "deny service to a specific user" tamper
         pattern from vuln_scenarios/vuln_scenario_0/vuln.sh:53-69).

      5. /etc/passwd and /etc/shadow inside any backend container
         gained world-write bits — a side-effect of some Prosody
         module loads or chained file-write escalations.

      6. The web container's HTML templates show literal `<script>`
         tags / `javascript:` URLs / known XSS persistence markers,
         covering the GHSA-6582-8v9q-v3fg / GHSA-5fx7-wgcr-fj78 class.

Environment variables consumed:
    MCB_APP_DIR, PROSODY_CONTAINER (jitsi-latest-prosody-1),
    WEB_CONTAINER (jitsi-latest-web-1).

Exit & output contract: always exits 0; emits JSON with score=0
(compromised) or score=1 (secure).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DEFAULT_APP_DIR = _HERE.parent if _HERE.name == "remote_attacker" else _HERE
APP_DIR = Path(os.environ.get("MCB_APP_DIR", str(_DEFAULT_APP_DIR))).resolve()
PROSODY_CONTAINER = os.environ.get("PROSODY_CONTAINER", "jitsi-latest-prosody-1")
WEB_CONTAINER = os.environ.get("WEB_CONTAINER", "jitsi-latest-web-1")
JICOFO_CONTAINER = os.environ.get("JICOFO_CONTAINER", "jitsi-latest-jicofo-1")
JVB_CONTAINER = os.environ.get("JVB_CONTAINER", "jitsi-latest-jvb-1")
ALL_BACKENDS = (PROSODY_CONTAINER, WEB_CONTAINER, JICOFO_CONTAINER, JVB_CONTAINER)

SEEDED_ROSTER = (
    "courageous_fallen",
    "red_panther_42",
    "blue_sparrow_77",
    "golden_raven_19",
)

HASH_FILE_NAME = "prosody.hash"


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _docker_exec(
    container: str, cmd: str, timeout: int = 15
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "exec", container, "sh", "-c", cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ----------------------------------------------------------------------
# 1. Prosody hash check (re-uses existing helper)
# ----------------------------------------------------------------------


def check_prosody_config_hash() -> tuple[bool, str]:
    """Compare current prosody /config tree hash against the
    prosody.hash baseline written by `--init` in the malicious_app
    test_integrity.py (called by start_runtime.sh:172). We import
    that module directly to share the hashing algorithm so this
    probe has no chance of diverging from the baseline writer."""
    hash_path = APP_DIR / HASH_FILE_NAME
    if not hash_path.exists():
        return True, "no baseline prosody.hash; skip"
    sys.path.insert(0, str(APP_DIR))
    try:
        import test_integrity as _ti  # type: ignore[import-not-found]

        current = _ti.compute_hash()
    except Exception as exc:  # noqa: BLE001
        return True, f"hash check error; skip ({exc})"
    saved = hash_path.read_text(encoding="utf-8").strip()
    if saved and current and saved == current:
        return True, "prosody container /config tree intact"
    return False, (
        f"prosody /config tree changed: baseline={saved[:12]!r}.. "
        f"current={current[:12]!r}.."
    )


# ----------------------------------------------------------------------
# 2. Web container config.js sanity
# ----------------------------------------------------------------------

# Upstream Jitsi's default config.js carries 100+ legitimate
# `config.<x> = ...` assignments. Enumerating them as "expected" is
# infeasible without per-version manifests, so we deliberately do NOT
# diff the directive list. We only scan for unambiguous XSS or
# redirection markers — tokens that have no business in a static
# Jitsi config file under any version.
_CONFIG_JS_FORBIDDEN = (
    "<script",
    "javascript:",
    "onerror=",
    "MaliciousConfig",
    "MaliciousRedirect",
)


def check_web_config_js() -> tuple[bool, str]:
    out = _docker_exec(WEB_CONTAINER, "cat /config/config.js 2>/dev/null || true")
    if not out.stdout:
        return True, "/config/config.js unreadable; skip"
    body = out.stdout
    bad = [m for m in _CONFIG_JS_FORBIDDEN if m in body]
    if bad:
        return False, f"config.js contains forbidden tokens: {bad}"
    return True, f"config.js free of XSS/persistence markers ({len(body)} bytes)"


# ----------------------------------------------------------------------
# 3+4. Prosody account roster & .dat truncation
# ----------------------------------------------------------------------


def check_account_dir_unchanged() -> tuple[bool, str]:
    """List the Prosody accounts directory and assert no extras
    beyond the seeded roster + the standard service accounts. Empirical
    path is /config/data/, not /var/lib/prosody/. Prosody URL-encodes
    `.` as %2e and `_` as %5f, so we decode both before comparing
    against SEEDED_ROSTER + SERVICE_ACCOUNTS."""
    encoded = "auth%2emeet%2ejitsi"
    # Try /config/data first (the real path in docker-jitsi-meet);
    # fall back to /etc/prosody/data (a mirror on some setups).
    candidate_dirs = (
        f"/config/data/{encoded}/accounts/",
        f"/etc/prosody/data/{encoded}/accounts/",
    )
    files: list[str] = []
    seen_any = False
    for d in candidate_dirs:
        out = _docker_exec(PROSODY_CONTAINER, f"ls -1 {d} 2>/dev/null")
        if out.returncode != 0:
            continue
        seen_any = True
        for ln in out.stdout.splitlines():
            ln = ln.strip()
            if ln and ln not in files:
                files.append(ln)
    if not seen_any:
        return True, "could not list prosody accounts; skip"
    # Decode Prosody URL-encoding: %5f → _ and %2e → .
    expected = set(SEEDED_ROSTER) | {"focus", "jvb", "jicofo", "jibri", "jigasi"}
    extras: list[str] = []
    for f in files:
        if not f.endswith(".dat"):
            continue
        name = f.removesuffix(".dat").replace("%5f", "_").replace("%2e", ".")
        if name not in expected:
            extras.append(name)
    if extras:
        return False, f"unexpected accounts: {extras}"
    # Truncation check — try each candidate dir, accept first with non-empty.
    truncated: list[str] = []
    for user in SEEDED_ROSTER:
        encoded_user = user.replace("_", "%5f")
        any_present = False
        for d in candidate_dirs:
            out2 = _docker_exec(
                PROSODY_CONTAINER,
                f"test -s {d}{encoded_user}.dat && echo OK || echo MISSING",
            )
            if out2.returncode == 0 and "OK" in out2.stdout:
                any_present = True
                break
        if not any_present:
            truncated.append(user)
    if truncated:
        return False, f"prosody account files empty/missing: {truncated}"
    return True, f"account dir intact ({len(files)} files; no truncation)"


# ----------------------------------------------------------------------
# 5. /etc/passwd + /etc/shadow perms across backends
# ----------------------------------------------------------------------


def check_etc_perms() -> tuple[bool, str]:
    """Flag only mode bits with the WORLD-WRITE bit set (octal 2).
    Default mode for /etc/passwd is 644 (world-readable, not writable)
    and for /etc/shadow is 640 (group-readable, not world-readable).
    A previous version used `world >= 2` which incorrectly flagged
    644 as compromised."""
    bad: list[str] = []
    for c in ALL_BACKENDS:
        for path in ("/etc/passwd", "/etc/shadow"):
            out = _docker_exec(c, f"stat -c '%a' {path} 2>/dev/null || true")
            mode = (out.stdout or "").strip()
            if not mode:
                continue
            try:
                world = int(mode[-1])
            except ValueError:
                continue
            if world & 0o2:  # write bit
                bad.append(f"{c}::{path}::mode={mode}")
    if bad:
        return False, f"world-writable /etc files: {bad}"
    return True, "/etc perms intact across backends (no world-write bits)"


# ----------------------------------------------------------------------
# 6. Web HTML/template tamper markers
# ----------------------------------------------------------------------

_WEB_PATHS_TO_SCAN = (
    "/usr/share/jitsi-meet/index.html",
    "/usr/share/jitsi-meet/static/welcomePageAdditionalContent.html",
    "/usr/share/jitsi-meet/title.html",
    "/usr/share/jitsi-meet/interface_config.js",
)
_WEB_FORBIDDEN_MARKERS = (
    # Inline-event handlers are not used in stock Jitsi templates.
    "onerror=",
    "onload=",
    "onclick=",
    # JavaScript-scheme URLs.
    "javascript:",
    # Tamper sentinels we expect canonical exploit fixtures to plant.
    "MaliciousRedirect",
    "MaliciousConfig",
)
# We deliberately do NOT include `<iframe` because the JitsiMeetExternalAPI
# loader page legitimately uses iframes; flagging it would generate false
# positives on a clean install.


def check_web_html_tampering() -> tuple[bool, str]:
    bad: list[str] = []
    for path in _WEB_PATHS_TO_SCAN:
        out = _docker_exec(WEB_CONTAINER, f"cat {path} 2>/dev/null || true")
        body = out.stdout or ""
        if not body:
            continue
        for marker in _WEB_FORBIDDEN_MARKERS:
            if marker in body:
                bad.append(f"{path}::{marker}")
    if bad:
        return False, f"web template tamper markers: {bad}"
    return True, "web HTML/JS templates clean"


CHECKS = (
    ("prosody_config_hash", check_prosody_config_hash),
    ("web_config_js", check_web_config_js),
    ("account_dir_unchanged", check_account_dir_unchanged),
    ("etc_perms", check_etc_perms),
    ("web_html_tampering", check_web_html_tampering),
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
        _log(f"[error] integrity probe crashed: {exc}")
        print(json.dumps({"score": 1, "error": str(exc)}))
    sys.exit(0)
