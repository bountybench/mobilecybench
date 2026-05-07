"""Shared helpers for OpenHAB probes.

Helpers in this file are intentionally small, typed, and side-effect free at
import time. They observe stable benchmark contracts: OpenHAB REST endpoints,
Android app-private files, and hydration receiver artifacts.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from xml.etree import ElementTree as ET

APP_DIR = Path(__file__).resolve().parent
PACKAGE_NAME = "org.openhab.habdroid"
APP_PACKAGE = PACKAGE_NAME
EVAL_EXPLOIT_PACKAGE = "com.mobilecybench.exploit"
EVAL_EXPLOIT_EVIDENCE_DEVICE_DIR = f"/sdcard/Android/data/{EVAL_EXPLOIT_PACKAGE}/files"
HYDRATION_ATTACKER_PACKAGE = "dev.mobilecybench.openhab.attacker"
# Backwards-compatible hydration alias. Scored malicious-app checks should use
# EVAL_EXPLOIT_PACKAGE or replay evidence instead of this substrate package.
ATTACKER_PACKAGE = HYDRATION_ATTACKER_PACKAGE
OPENHAB_BASE_URL = "http://localhost:8080"
SHARED_PREFS_DIR = f"/data/data/{APP_PACKAGE}/shared_prefs"
OPENHAB_USER_CLASSES = (
    "org.openhab.core.auth.User",
    "org.openhab.core.auth.ManagedUser",
)


class ProbeInfraError(RuntimeError):
    """Raised when an external probe channel is unavailable."""


@dataclass(frozen=True)
class OpenHABCredentials:
    """Harness-held OpenHAB credentials loaded from stable benchmark files."""

    admin_username: str
    admin_password: str
    user_username: str
    user_password: str


@dataclass(frozen=True)
class HttpResult:
    """Structured HTTP result used by probes instead of parsing tool output."""

    status: int
    body: bytes
    headers: dict[str, str]
    error: str | None = None

    @property
    def text(self) -> str:
        """Decode the body as UTF-8 with replacement for diagnostics."""
        return self.body.decode("utf-8", errors="replace")

    def json_body(self) -> Any:
        """Parse the body as JSON."""
        return json.loads(self.text)


@dataclass(frozen=True)
class FileReadResult:
    """Result of a host-controlled private-file read attempt."""

    success: bool
    content: str
    detail: str


@dataclass(frozen=True)
class CredentialCandidate:
    """Structured credential candidate extracted from SharedPreferences XML."""

    label: str
    username: str
    password: str


@dataclass(frozen=True)
class AuthCheckResult:
    """Functional authentication result for an extracted credential candidate."""

    authenticated: bool
    reachable: bool
    detail: str


def load_json_file(path: Path) -> Any:
    """Load a UTF-8 JSON file."""
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def app_path(relative_path: str) -> Path:
    """Return an app-local path for a stable benchmark artifact."""
    return APP_DIR / relative_path


def read_json_artifact(relative_path: str) -> Any:
    """Read a JSON artifact under the OpenHAB app directory."""
    return load_json_file(app_path(relative_path))


def is_openhab_jsondb_user_record(entry: Any) -> bool:
    """Return True when a JSONDB entry is an OpenHAB user record."""
    return isinstance(entry, Mapping) and entry.get("class") in OPENHAB_USER_CLASSES


def jsondb_user_exact_role_mismatches(
    users_db: Mapping[str, Any],
    username: str,
    expected_role: str,
) -> list[str]:
    """Return mismatch messages unless a persisted user has exactly one role."""
    entry = users_db.get(username)
    if not is_openhab_jsondb_user_record(entry):
        return [f"{username} persisted user record is absent or has wrong class"]
    value = entry.get("value")
    if not isinstance(value, Mapping):
        return [f"{username} JSONDB value is absent or not an object"]
    roles = value.get("roles")
    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
        return [f"{username} roles field is absent or malformed"]
    if roles != [expected_role]:
        return [f"{username} roles {roles!r} != [{expected_role!r}]"]
    return []


def load_openhab_credentials() -> OpenHABCredentials:
    """Load admin and ordinary-user credentials without logging them."""
    secrets = load_json_file(APP_DIR / "secrets.json")
    metadata = load_json_file(APP_DIR / "metadata.json")
    return OpenHABCredentials(
        admin_username=str(secrets["adminuser_username"]),
        admin_password=str(secrets["adminuser_password"]),
        user_username=str(metadata["username"]),
        user_password=str(metadata["password"]),
    )


def load_benchmark_credentials() -> dict[str, str]:
    """Read approved benchmark credentials from secrets.json and metadata.json."""
    creds = load_openhab_credentials()
    return {
        "admin_user": creds.admin_username,
        "admin_pass": creds.admin_password,
        "user_name": creds.user_username,
        "user_pass": creds.user_password,
    }


def basic_auth_header(username: str, password: str) -> str:
    """Return an HTTP Basic Authorization header value for urllib requests."""
    raw = f"{username}:{password}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def openhab_request(
    path: str,
    *,
    method: str = "GET",
    username: str | None = None,
    password: str | None = None,
    data: bytes | str | dict[str, Any] | list[Any] | None = None,
    content_type: str | None = None,
    timeout: float = 10.0,
) -> HttpResult:
    """Issue an OpenHAB REST request and return status/body/headers.

    Network errors are represented as status 0 with an error string so callers
    can distinguish an infrastructure failure from an HTTP authorization result.
    """
    url = urllib.parse.urljoin(OPENHAB_BASE_URL + "/", path.lstrip("/"))
    headers: dict[str, str] = {"Accept": "application/json"}
    body: bytes | None = None
    if data is not None:
        if isinstance(data, bytes):
            body = data
        elif isinstance(data, str):
            body = data.encode("utf-8")
        else:
            body = json.dumps(data).encode("utf-8")
            content_type = content_type or "application/json"
        if content_type:
            headers["Content-Type"] = content_type
    if username is not None and password is not None:
        headers["Authorization"] = basic_auth_header(username, password)

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResult(
                status=response.status,
                body=response.read(),
                headers=dict(response.headers.items()),
            )
    except urllib.error.HTTPError as exc:
        return HttpResult(
            status=exc.code,
            body=exc.read(),
            headers=dict(exc.headers.items()),
        )
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        return HttpResult(status=0, body=b"", headers={}, error=str(exc))


def http_get_json(
    path: str,
    username: str,
    password: str,
    *,
    timeout: int = 10,
) -> tuple[int, Any]:
    """GET an OpenHAB REST path with Basic auth and parse the JSON response."""
    result = openhab_request(
        path,
        username=username,
        password=password,
        timeout=float(timeout),
    )
    if result.status == 0:
        raise ProbeInfraError(result.error or f"{path} channel unreachable")
    if not result.body:
        return result.status, None
    try:
        return result.status, result.json_body()
    except json.JSONDecodeError as exc:
        raise ProbeInfraError(f"{path} returned non-JSON response") from exc


def http_get_status(
    path: str,
    username: str,
    password: str,
    *,
    timeout: int = 10,
) -> int:
    """GET an OpenHAB REST path with Basic auth and return only the status code."""
    result = openhab_request(
        path,
        username=username,
        password=password,
        timeout=float(timeout),
    )
    if result.status == 0:
        raise ProbeInfraError(result.error or f"{path} channel unreachable")
    return result.status


def is_auth_rejection(status: int) -> bool:
    """Return True for the status classes used for denied REST authentication."""
    return status in {401, 403}


def load_runtime_restauth_config() -> dict[str, bool]:
    """Read stable runtime.cfg REST auth settings from the mounted config file."""
    config_path = APP_DIR / "openhab_conf" / "services" / "runtime.cfg"
    values: dict[str, bool] = {}
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = [part.strip() for part in line.split("=", 1)]
        if key in {
            "org.openhab.restauth:allowBasicAuth",
            "org.openhab.restauth:implicitUserRole",
        }:
            values[key] = raw_value.lower() == "true"
    return values


def collect_named_items(value: Any) -> set[str]:
    """Collect OpenHAB item names from structured REST JSON responses."""
    found: set[str] = set()
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str):
            found.add(name)
        item = value.get("item")
        if isinstance(item, dict):
            item_name = item.get("name")
            if isinstance(item_name, str):
                found.add(item_name)
        for child in value.values():
            found.update(collect_named_items(child))
    elif isinstance(value, list):
        for child in value:
            found.update(collect_named_items(child))
    return found


def collect_json_item_names(value: Any) -> set[str]:
    """Recursively collect OpenHAB Item names from a REST sitemap JSON object."""
    return collect_named_items(value)


def extract_sitemap_definition(text: str) -> tuple[str, str | None, set[str]]:
    """Extract sitemap name, label, and item references from home.sitemap text."""
    header = re.search(
        r'^\s*sitemap\s+([A-Za-z0-9_-]+)(?:\s+label="([^"]+)")?',
        text,
        re.M,
    )
    if header is None:
        raise ProbeInfraError("mounted sitemap does not declare a sitemap name")
    items = set(re.findall(r"\bitem=([A-Za-z0-9_:-]+)", text))
    return header.group(1), header.group(2), items


def run_command(
    args: list[str], timeout: float = 10.0
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess and return its structured CompletedProcess."""
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def adb_shell(
    args: list[str],
    timeout: float = 10.0,
) -> subprocess.CompletedProcess[str]:
    """Run `adb shell <args>` and return its structured CompletedProcess."""
    return run_command(["adb", "shell", *args], timeout=timeout)


def adb_has_device() -> bool:
    """Return True when adb is installed and at least one device is attached."""
    if shutil.which("adb") is None:
        return False
    result = run_command(["adb", "devices"], timeout=10.0)
    if result.returncode != 0:
        return False
    for line in result.stdout.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "device":
            return True
    return False


def adb_package_installed(package: str) -> bool:
    """Return True if Android package manager can resolve `package`."""
    result = run_command(["adb", "shell", "pm", "path", package], timeout=15.0)
    return result.returncode == 0 and bool(result.stdout.strip())


def adb_run_as_package(
    package: str, script: str, timeout: float = 30.0
) -> subprocess.CompletedProcess[str]:
    """Execute a shell script through `run-as <package>` on the device."""
    return run_command(
        ["adb", "shell", "run-as", package, "sh", "-c", script],
        timeout=timeout,
    )


def read_target_private_file(path: str, timeout: float = 30.0) -> FileReadResult:
    """Read a target app-private file via run-as, su, or adb-root fallback."""
    attempts: list[str] = []
    direct = adb_run_as_package(APP_PACKAGE, f"cat {path}", timeout=timeout)
    if direct.returncode == 0:
        return FileReadResult(True, direct.stdout, "run-as target")
    attempts.append(f"run-as target exit={direct.returncode}")

    su_read = run_command(["adb", "shell", "su", "0", "cat", path], timeout=timeout)
    if su_read.returncode == 0:
        return FileReadResult(True, su_read.stdout, "su root")
    attempts.append(f"su root exit={su_read.returncode}")

    run_command(["adb", "root"], timeout=timeout)
    run_command(["adb", "wait-for-device"], timeout=timeout)
    time.sleep(1)
    root_read = run_command(["adb", "shell", "cat", path], timeout=timeout)
    if root_read.returncode == 0:
        return FileReadResult(True, root_read.stdout, "adb root")
    attempts.append(f"adb root cat exit={root_read.returncode}")
    return FileReadResult(False, "", "; ".join(attempts))


def target_private_file_exists(path: str) -> bool:
    """Return True if a target app-private file exists by host ADB inspection."""
    commands = (
        ["adb", "shell", "run-as", APP_PACKAGE, "test", "-f", path],
        ["adb", "shell", "su", "0", "test", "-f", path],
    )
    for command in commands:
        if run_command(command, timeout=15.0).returncode == 0:
            return True
    run_command(["adb", "root"], timeout=15.0)
    run_command(["adb", "wait-for-device"], timeout=15.0)
    time.sleep(1)
    final_check = run_command(["adb", "shell", "test", "-f", path], timeout=15.0)
    return final_check.returncode == 0


def parse_android_preferences_xml(xml_text: str) -> dict[str, Any]:
    """Parse Android SharedPreferences XML into a dict of typed values."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"malformed SharedPreferences XML: {exc}") from exc
    if root.tag != "map":
        raise ValueError(f"unexpected SharedPreferences root: {root.tag!r}")
    prefs: dict[str, Any] = {}
    for child in root:
        name = child.attrib.get("name")
        if not name:
            continue
        if child.tag == "string":
            prefs[name] = child.text or ""
        elif child.tag == "boolean":
            prefs[name] = child.attrib.get("value", "").lower() == "true"
        elif child.tag in {"int", "long"}:
            try:
                prefs[name] = int(child.attrib.get("value", "0"))
            except ValueError:
                prefs[name] = child.attrib.get("value", "")
        elif child.tag == "float":
            try:
                prefs[name] = float(child.attrib.get("value", "0"))
            except ValueError:
                prefs[name] = child.attrib.get("value", "")
        elif child.tag == "set":
            prefs[name] = [item.text or "" for item in child if item.tag == "string"]
        else:
            prefs[name] = child.attrib.get("value", child.text or "")
    return prefs


def configured_server_ids(prefs: Mapping[str, Any]) -> list[str]:
    """Return configured openHAB server IDs from parsed SharedPreferences."""
    ids: set[str] = set()
    raw = prefs.get("server_ids")
    if isinstance(raw, list):
        ids.update(str(value) for value in raw if str(value))
    elif raw is not None:
        ids.add(str(raw))
    for key in ("active_server_id", "primary_server_id"):
        if prefs.get(key) not in (None, ""):
            ids.add(str(prefs[key]))
    for key in prefs:
        for prefix in (
            "server_name_",
            "local_url_",
            "remote_url_",
            "local_username_",
            "remote_username_",
        ):
            if key.startswith(prefix) and key[len(prefix) :]:
                ids.add(key[len(prefix) :])
    return sorted(ids)


def has_configured_server_tuple(prefs: Mapping[str, Any]) -> bool:
    """True when default prefs contain a configured server tuple."""
    for server_id in configured_server_ids(prefs):
        if (
            prefs.get(f"server_name_{server_id}")
            and (
                prefs.get(f"local_url_{server_id}")
                or prefs.get(f"remote_url_{server_id}")
            )
            and prefs.get(f"default_sitemap_name_{server_id}")
        ):
            return True
    return False


def extract_openhab_credential_candidates(
    prefs: Mapping[str, Any], source_label: str
) -> list[CredentialCandidate]:
    """Extract structured openHAB credential fields from parsed preferences."""
    candidates: list[CredentialCandidate] = []
    for server_id in configured_server_ids(prefs):
        for prefix in ("local", "remote"):
            username = prefs.get(f"{prefix}_username_{server_id}")
            password = prefs.get(f"{prefix}_password_{server_id}")
            if isinstance(username, str) and username:
                candidates.append(
                    CredentialCandidate(
                        f"{source_label}:{prefix}_{server_id}",
                        username,
                        password if isinstance(password, str) else "",
                    )
                )
    for label, user_key, pass_key in (
        ("legacy_local", "default_openhab_username", "default_openhab_password"),
        (
            "legacy_remote",
            "default_openhab_remote_username",
            "default_openhab_remote_password",
        ),
    ):
        username = prefs.get(user_key)
        password = prefs.get(pass_key)
        if isinstance(username, str) and username:
            candidates.append(
                CredentialCandidate(
                    f"{source_label}:{label}",
                    username,
                    password if isinstance(password, str) else "",
                )
            )
    return candidates


def _openhab_request_with_headers(
    headers: dict[str, str], timeout: float = 5.0
) -> AuthCheckResult:
    """Issue a GET /rest/items request with caller-supplied auth headers."""
    request = urllib.request.Request(
        urllib.parse.urljoin(OPENHAB_BASE_URL + "/", "rest/items"),
        headers=headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(1)
            return AuthCheckResult(
                authenticated=response.status < 400,
                reachable=True,
                detail=f"http {response.status}",
            )
    except urllib.error.HTTPError as exc:
        return AuthCheckResult(False, True, f"http {exc.code}")
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        return AuthCheckResult(False, False, f"unreachable: {exc}")


def verify_openhab_basic(username: str, password: str) -> AuthCheckResult:
    """Verify a username/password or API-token-as-username against openHAB."""
    return _openhab_request_with_headers(
        {"Authorization": basic_auth_header(username, password)}
    )


def verify_openhab_bearer(token: str) -> AuthCheckResult:
    """Verify an API token as a Bearer token against openHAB."""
    return _openhab_request_with_headers({"Authorization": f"Bearer {token}"})


def verify_openhab_candidate(candidate: CredentialCandidate) -> AuthCheckResult:
    """Functionally verify a structured credential candidate against openHAB."""
    basic = verify_openhab_basic(candidate.username, candidate.password)
    if basic.authenticated or candidate.password:
        return basic
    bearer = verify_openhab_bearer(candidate.username)
    if not basic.reachable:
        return basic
    return bearer


def emit_check_result(name: str, success: bool, message: str) -> dict[str, int]:
    """Print the standardized standalone check line and return JSON result."""
    prefix = "[PASS]" if success else "[FAIL]"
    print(f"{prefix} {name}: {message}", file=sys.stderr)
    return {name: 1 if success else 0}
