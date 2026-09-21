"""Shared cross-app probe helpers (Phase 0.2).

Pure functions extracted from the union of:

  - ``apps/home-assistant-android/probe_lib.py``
  - ``apps/wallabag/probe_common.py``

Per-app ``probe_lib.py`` can re-export from this module to consolidate
duplicated helpers, while keeping app-specific constants (server names,
paths, package names) in the app's own probe_lib.

Categories:
  - Output & logging: ``log``, ``emit_error``, ``emit_check_result``,
    ``stream_digest``, ``token_digest``
  - Subprocess: ``run_command``
  - Docker: ``docker_exec``, ``docker_inspect``, ``docker_running``,
    ``docker_healthy``, ``docker_exec_cat``, ``docker_exec_sha256``
  - ADB / device: ``adb_root_cat``, ``adb_root_shell``,
    ``scan_shared_storage_for_text``
  - Android XML: ``read_shared_prefs_map``
  - Baseline manifest: ``load_baseline_at``, ``diff_against_baseline``
  - HTTP: ``ssl_unverified_context``, ``http_json``

Anti-pattern compliance: every helper here is observer-only and parses
structured data where possible (``probe-runs-the-exploit`` and
``brittle-substring-on-tool-output`` anti-patterns). Helpers that read
state via ``adb shell su 0`` are explicit about needing rooted access.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Output / logging
# ---------------------------------------------------------------------------


def log(message: str) -> None:
    """Write a debug/diagnostic line to stderr.

    Probes use this for non-result output. The standard probe contract emits
    structured ``{"score": ...}`` JSON on stdout; everything else goes here.
    """
    print(message, file=sys.stderr)


def emit_error(reason: str) -> dict[str, Any]:
    """Return a uniform infrastructure-error dict for entrypoints to emit."""
    return {"score": 0, "error": reason}


def emit_check_result(name: str, success: bool, message: str) -> dict[str, Any]:
    """Standard check-result emission used by per-probe ``check_*.py``.

    Returns the dict so test_*.py aggregators can also consume it. Prints a
    one-line ``[PASS]`` / ``[FAIL]`` to stderr matching the canonical HA shape.
    """
    prefix = "[PASS]" if success else "[FAIL]"
    log(f"{prefix} {name}: {message}")
    return {"name": name, "success": bool(success), "message": message}


def stream_digest(value: str | bytes) -> str:
    """Compact ``len=N sha256=ABC`` digest string for [DEBUG] log lines."""
    if isinstance(value, str):
        raw = value.encode("utf-8", errors="replace")
    else:
        raw = value
    digest = hashlib.sha256(raw).hexdigest()[:12]
    return f"len={len(raw)} sha256={digest}"


def token_digest(token: str) -> str:
    """Compact digest of a credential string. Never logs the credential itself."""
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
    return f"len={len(token)} sha256={digest}"


# ---------------------------------------------------------------------------
# Subprocess
# ---------------------------------------------------------------------------


def run_command(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and emit a standard [DEBUG] line.

    Returns the CompletedProcess. Caller decides what to do with returncode.
    """
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    log(
        f"[DEBUG] {' '.join(args[:4])} exit={result.returncode} "
        f"stdout={stream_digest(result.stdout)} stderr={stream_digest(result.stderr)}"
    )
    return result


# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------


def docker_exec(
    container: str, args: list[str], timeout: int = 10
) -> subprocess.CompletedProcess[str]:
    """Run ``docker exec <container> <args>`` and return the CompletedProcess."""
    return run_command(["docker", "exec", container, *args], timeout=timeout)


def docker_inspect(container: str, fmt: str) -> str:
    """Run ``docker inspect --format <fmt> <container>`` and return stripped stdout.

    Returns empty string on failure (caller can interpret).
    """
    result = run_command(["docker", "inspect", "--format", fmt, container])
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def docker_running(container: str) -> bool:
    """True iff ``{{.State.Running}}`` is ``true`` for the container."""
    return docker_inspect(container, "{{.State.Running}}").lower() == "true"


def docker_healthy(container: str) -> bool:
    """True iff ``{{.State.Health.Status}}`` is ``healthy`` for the container."""
    return docker_inspect(container, "{{.State.Health.Status}}").lower() == "healthy"


def docker_exec_cat(container: str, path: str) -> str:
    """Read a text file from inside a docker container.

    Raises RuntimeError on failure.
    """
    result = docker_exec(container, ["cat", path])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"could not read {path}")
    return result.stdout


def docker_exec_sha256(container: str, path: str) -> str:
    """SHA-256 hex digest of a file inside the container, or empty on failure."""
    try:
        content = docker_exec_cat(container, path)
    except RuntimeError:
        return ""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# ADB / device
# ---------------------------------------------------------------------------
# These helpers require rooted ADB shell access (``su 0 ...``). The
# benchmark harness's ADB proxy may block ``su`` for the agent — these
# helpers are intended for the *probe* (verifier) side, not for exploits.


def adb_root_cat(path: str, timeout: int = 10) -> str:
    """Read a file from the device as root via ADB.

    Raises RuntimeError on failure. Probe-side use only.
    """
    result = subprocess.run(
        ["adb", "shell", "su", "0", "cat", path],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            (result.stderr or result.stdout or "").strip()
            or f"adb cat rc={result.returncode}"
        )
    return result.stdout.replace("\r", "").strip()


def adb_root_shell(script: str, timeout: int = 30) -> tuple[bool, str]:
    """Execute a shell script on the device as root.

    Returns ``(success, output)`` where ``output`` is stdout|stderr stripped
    of carriage returns. ``script`` is fed to ``sh`` via stdin so multi-line
    scripts can use ``set -e`` etc.
    """
    result = subprocess.run(
        ["adb", "shell", "su", "0", "sh"],
        capture_output=True,
        text=True,
        input=f"set -e\n{script}\n",
        timeout=timeout,
    )
    out = (result.stdout or result.stderr or "").replace("\r", "").strip()
    return result.returncode == 0, out


def scan_shared_storage_for_text(
    needle: str, *, roots: Iterable[str] = ("/sdcard",)
) -> bool:
    """Recursive grep for ``needle`` under shared-storage roots on the device.

    Returns True if any file in any root contains the literal string. Useful
    for canary detection (``probe-without-baseline`` anti-pattern: pair with
    a baseline manifest of pre-existing canaries). Requires root.
    """
    if not needle:
        return False
    needle_q = shlex.quote(needle)
    for root in roots:
        ok, listing = adb_root_shell(
            f"test -d {root} && grep -R -a -F -q -- {needle_q} "
            f"{shlex.quote(root)} && echo HIT || true",
            timeout=90,
        )
        if not ok:
            raise RuntimeError(f"shared storage scan failed under {root}: {listing}")
        if "HIT" in listing:
            return True
    return False


# ---------------------------------------------------------------------------
# Android shared-preferences XML parsing
# ---------------------------------------------------------------------------


def read_shared_prefs_map(path: str) -> dict[str, Any]:
    """Parse an Android SharedPreferences XML file into a flat key→value map.

    The XML lives under ``/data/data/<pkg>/shared_prefs/<pkg>_preferences.xml``;
    this helper reads it via ``adb_root_cat`` and parses with stdlib
    ``ElementTree`` (no third-party deps). Returns empty dict if the file is
    empty or missing.
    """
    raw = adb_root_cat(path)
    if not raw:
        return {}
    root = ET.fromstring(raw)
    out: dict[str, Any] = {}
    for child in root:
        key = child.attrib.get("name")
        if not key:
            continue
        if child.tag == "string":
            out[key] = child.text or ""
        elif child.tag in {"boolean", "int", "long", "float"}:
            out[key] = child.attrib.get("value", "")
        else:
            out[key] = child.attrib.get("value", child.text or "")
    return out


# ---------------------------------------------------------------------------
# Baseline manifest helpers
# ---------------------------------------------------------------------------


def load_baseline_at(path: Path, required_keys: Iterable[str] = ()) -> dict[str, Any]:
    """Load a baseline_manifest.json from ``path``, validating required keys.

    Per-app probe_libs typically wrap this with their own ``BASELINE_FILE``
    constant: see HA's ``load_baseline()`` in
    ``apps/home-assistant-android/probe_lib.py``.
    """
    with path.open(encoding="utf-8") as handle:
        baseline = json.load(handle)
    missing = [key for key in required_keys if key not in baseline]
    if missing:
        raise ValueError(f"baseline missing keys: {', '.join(missing)}")
    return baseline


def diff_against_baseline(live: Any, baseline: Any) -> tuple[Any, Any]:
    """Compute (added, removed) when comparing live state to a baseline.

      - Sets / frozensets: returns (live - baseline, baseline - live).
      - Dicts: returns (keys-added, keys-removed).
      - Lists: returns (live - baseline, baseline - live) treating both as sets.
      - Any other type pair: raises TypeError.

    The set semantics are deliberately strict: probes must opt into a typed
    diff, not silently coerce. This avoids the
    ``brittle-substring-on-tool-output`` anti-pattern.
    """
    if isinstance(live, (set, frozenset)) or isinstance(baseline, (set, frozenset)):
        live_set = set(live)
        baseline_set = set(baseline)
        return live_set - baseline_set, baseline_set - live_set
    if isinstance(live, dict) and isinstance(baseline, dict):
        return (
            set(live.keys()) - set(baseline.keys()),
            set(baseline.keys()) - set(live.keys()),
        )
    if isinstance(live, list) and isinstance(baseline, list):
        live_set = set(live)
        baseline_set = set(baseline)
        return live_set - baseline_set, baseline_set - live_set
    raise TypeError(f"unsupported diff types: {type(live)}, {type(baseline)}")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def ssl_unverified_context() -> ssl.SSLContext:
    """SSL context that skips cert verification.

    Used by probes against the benchmark's TLS-proxied backends, which use
    self-signed certs. Probes only — never use in agent code.
    """
    return ssl._create_unverified_context()


def http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
    timeout: int = 10,
    verify_ssl: bool = False,
) -> tuple[int, Any]:
    """Send a JSON request, return ``(status_code, parsed_body)``.

    On URLError returns ``(0, str(reason))``. JSON-decode errors fall back to
    raw response text. Default ``verify_ssl=False`` for benchmark backends;
    set True for any external endpoint.
    """
    body = None
    final_headers = headers.copy() if headers else {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        final_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=body, headers=final_headers, method=method
    )
    try:
        ctx = None if verify_ssl else ssl_unverified_context()
        with urllib.request.urlopen(request, timeout=timeout, context=ctx) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = raw
        return exc.code, parsed
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)


__all__ = [
    "adb_root_cat",
    "adb_root_shell",
    "diff_against_baseline",
    "docker_exec",
    "docker_exec_cat",
    "docker_exec_sha256",
    "docker_healthy",
    "docker_inspect",
    "docker_running",
    "emit_check_result",
    "emit_error",
    "http_json",
    "load_baseline_at",
    "log",
    "read_shared_prefs_map",
    "run_command",
    "scan_shared_storage_for_text",
    "ssl_unverified_context",
    "stream_digest",
    "token_digest",
]
