"""Shared helpers for OpenHAB probes.

Helpers in this file are intentionally small, typed, and side-effect free at
import time. They observe stable benchmark contracts: OpenHAB REST endpoints,
Docker runtime metadata, raw TCP sockets, and MQTT protocol responses.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
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
OPENHAB_CONTAINER = "openhab"
MOSQUITTO_CONTAINER = "mosquitto"
SHARED_PREFS_DIR = f"/data/data/{APP_PACKAGE}/shared_prefs"
DEFAULT_PREFS_PATH = f"{SHARED_PREFS_DIR}/{APP_PACKAGE}_preferences.xml"
ENCRYPTED_SECRET_PREFS_PATH = f"{SHARED_PREFS_DIR}/secret_shared_prefs_encrypted.xml"
LEGACY_SECRET_PREFS_PATH = f"{SHARED_PREFS_DIR}/secret_shared_prefs.xml"
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
class SocketProbeResult:
    """Structured TCP probe result."""

    connected: bool
    banner: bytes
    error: str | None = None


@dataclass(frozen=True)
class MqttConnack:
    """Structured MQTT CONNACK result."""

    reached: bool
    return_code: int | None
    error: str | None = None


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


def load_metadata() -> dict[str, Any]:
    """Read metadata.json from the OpenHAB benchmark app directory."""
    metadata = read_json_artifact("metadata.json")
    if not isinstance(metadata, dict):
        raise ProbeInfraError("metadata.json did not contain an object")
    return metadata


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


def sha256_file(path: Path) -> str:
    """Compute SHA-256 for a local file without loading it all at once."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_snapshot(path: Path) -> dict[str, int | str]:
    """Return structured file identity fields used for baseline comparisons."""
    stat_result = path.stat()
    return {
        "sha256": sha256_file(path),
        "size": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
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


def load_seed_item_names() -> set[str]:
    """Load benchmark seed item names from the host-mounted JSONDB baseline."""
    item_db = load_json_file(
        APP_DIR / "openhab_userdata" / "jsondb" / "org.openhab.core.items.Item.json"
    )
    if not isinstance(item_db, dict):
        raise ValueError("seed item JSONDB is not an object")
    return {str(name) for name in item_db}


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


def adb_dumpsys_package(package_name: str = PACKAGE_NAME) -> str:
    """Return Android PackageManager metadata for an installed package.

    Raises RuntimeError when ADB, the device, or the requested package is not
    available. Callers should report that as an infrastructure error.
    """
    path_result = adb_shell(["pm", "path", package_name], timeout=15.0)
    if path_result.returncode != 0 or not path_result.stdout.strip():
        raise RuntimeError(f"{package_name} is not installed or adb is unavailable")
    result = adb_shell(["dumpsys", "package", package_name], timeout=30.0)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown adb error"
        raise RuntimeError(f"dumpsys package failed: {detail}")
    if not result.stdout.strip():
        raise RuntimeError("dumpsys package returned no metadata")
    return result.stdout


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


def adb_read_app_file(package_name: str, device_path: str, *, timeout: int = 10) -> str:
    """Read an app-private device file through benchmark-controlled adb."""
    if package_name != APP_PACKAGE:
        commands = (
            ["adb", "shell", "run-as", package_name, "cat", device_path],
            ["adb", "shell", "su", "0", "cat", device_path],
        )
        failures: list[str] = []
        for command in commands:
            try:
                proc = run_command(command, timeout=float(timeout))
            except FileNotFoundError as exc:
                raise ProbeInfraError("adb executable not found") from exc
            except subprocess.TimeoutExpired:
                failures.append(f"{command[:3]} timed out")
                continue
            if proc.returncode == 0:
                return proc.stdout
            failures.append(f"{command[:3]} exited {proc.returncode}")
        raise ProbeInfraError("; ".join(failures))

    try:
        result = read_target_private_file(device_path, timeout=float(timeout))
    except FileNotFoundError as exc:
        raise ProbeInfraError("adb executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeInfraError("adb file read timed out") from exc
    if not result.success:
        raise ProbeInfraError(result.detail)
    return result.content


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


def android_sdk_level() -> int | None:
    """Return the attached device SDK level, or None when unavailable."""
    result = run_command(
        ["adb", "shell", "getprop", "ro.build.version.sdk"],
        timeout=10.0,
    )
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


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


def parse_android_shared_preferences(xml_text: str) -> dict[str, object]:
    """Parse Android SharedPreferences XML into typed Python values."""
    try:
        return parse_android_preferences_xml(xml_text)
    except ValueError as exc:
        raise ProbeInfraError(str(exc)) from exc


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


def normalize_component(component: str, package_name: str = PACKAGE_NAME) -> str:
    """Normalize `package/class` component strings from PackageManager output."""
    package, _, activity = component.strip().partition("/")
    if not package or not activity:
        return component.strip()
    if activity.startswith("."):
        activity = f"{package}{activity}"
    elif "." not in activity:
        activity = f"{package}.{activity}"
    if package != package_name:
        return f"{package}/{activity}"
    return f"{package_name}/{activity}"


def component_class(component: str) -> str:
    """Return the class portion of a normalized Android component string."""
    return component.split("/", 1)[1] if "/" in component else component


def parse_resolved_component(
    stdout: str,
    package_name: str = PACKAGE_NAME,
) -> str | None:
    """Extract a `package/class` component token from PackageManager output."""
    for line in reversed(stdout.splitlines()):
        for token in reversed(line.strip().split()):
            if "/" not in token or "=" in token:
                continue
            return normalize_component(token.strip(), package_name)
    return None


@dataclass
class PackageComponent:
    """Parsed PackageManager metadata for one Android component."""

    name: str
    present: bool
    fields: dict[str, set[str]] = field(default_factory=dict)
    actions: set[str] = field(default_factory=set)
    categories: set[str] = field(default_factory=set)
    blocks: list[str] = field(default_factory=list)


_COMPONENT_FIELD_RE = re.compile(
    r"\b(?P<field>exported|enabled|permission)="
    r"(?P<value>\"[^\"]+\"|'[^']+'|[^,\s}\]]+)"
)
_QUOTED_ACTION_RE = re.compile(r'\bAction:\s+"(?P<value>[^"]+)"')
_QUOTED_CATEGORY_RE = re.compile(r'\bCategory:\s+"(?P<value>[^"]+)"')
_ACT_FIELD_RE = re.compile(r"\bact=(?P<value>[^,\s}\]]+)")
_CAT_FIELD_RE = re.compile(r"\bcat=\[(?P<value>[^\]]+)\]")


def full_component_name(name: str, package_name: str = PACKAGE_NAME) -> str:
    """Expand a PackageManager component name to a fully qualified class name."""
    if name.startswith("."):
        return f"{package_name}{name}"
    if name.startswith(f"{package_name}."):
        return name
    return f"{package_name}.{name}"


def _component_tokens(name: str, package_name: str = PACKAGE_NAME) -> set[str]:
    full_name = full_component_name(name, package_name)
    relative_name = f".{full_name.removeprefix(package_name + '.')}"
    return {
        full_name,
        f"{package_name}/{full_name}",
        f"{package_name}/{relative_name}",
        relative_name,
    }


_ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
_MANIFEST_COMPONENT_TAGS = {
    "activity",
    "activity-alias",
    "provider",
    "receiver",
    "service",
}


def _local_xml_tag(tag: str) -> str:
    """Return an XML tag without its namespace prefix."""
    return tag.rsplit("}", 1)[-1]


def _android_attr(element: ET.Element, name: str) -> str | None:
    """Read an android:* manifest attribute."""
    return element.attrib.get(f"{_ANDROID_NS}{name}")


def _iter_source_manifests() -> list[Path]:
    source_root = APP_DIR / "codebase" / "mobile" / "src"
    if not source_root.exists():
        return []
    return sorted(source_root.glob("*/AndroidManifest.xml"))


def source_manifest_component_metadata(
    component_name: str, package_name: str = PACKAGE_NAME
) -> PackageComponent:
    """Read component metadata declared in checked-in Android manifests.

    Android 35 PackageManager dumpsys output omits some explicit manifest
    fields, including exported=false and service permission values. Runtime
    checks still use dumpsys for component presence; this source view only
    supplies fields that dumpsys left unreported.
    """
    full_name = full_component_name(component_name, package_name)
    component = PackageComponent(name=full_name, present=False)
    for manifest_path in _iter_source_manifests():
        try:
            root = ET.parse(manifest_path).getroot()
        except ET.ParseError:
            continue
        application = root.find("application")
        if application is None:
            continue
        for child in application:
            if _local_xml_tag(child.tag) not in _MANIFEST_COMPONENT_TAGS:
                continue
            raw_name = _android_attr(child, "name")
            if not raw_name:
                continue
            if full_component_name(raw_name, package_name) != full_name:
                continue
            component.present = True
            component.blocks.append(str(manifest_path))
            for field_name in ("enabled", "exported", "permission"):
                value = _android_attr(child, field_name)
                if value is not None:
                    component.fields.setdefault(field_name, set()).add(value)
            for intent_filter in child:
                if _local_xml_tag(intent_filter.tag) != "intent-filter":
                    continue
                for intent_child in intent_filter:
                    value = _android_attr(intent_child, "name")
                    if not value:
                        continue
                    intent_tag = _local_xml_tag(intent_child.tag)
                    if intent_tag == "action":
                        component.actions.add(value)
                    elif intent_tag == "category":
                        component.categories.add(value)
    return component


def component_with_source_manifest_fallback(
    package_dump: str, component_name: str, package_name: str = PACKAGE_NAME
) -> PackageComponent:
    """Return PackageManager metadata with source manifest gaps filled.

    The installed package dump remains authoritative for presence. Source
    manifests only fill omitted fields/actions/categories; explicit runtime
    values are left intact so real mismatches still fail probes.
    """
    runtime = parse_component_metadata(package_dump, component_name, package_name)
    if not runtime.present:
        return runtime

    source = source_manifest_component_metadata(component_name, package_name)
    if not source.present:
        return runtime

    merged = PackageComponent(
        name=runtime.name,
        present=True,
        fields={key: set(values) for key, values in runtime.fields.items()},
        actions=set(runtime.actions),
        categories=set(runtime.categories),
        blocks=list(runtime.blocks),
    )
    for field_name, values in source.fields.items():
        if not merged.fields.get(field_name):
            merged.fields[field_name] = set(values)
    if not merged.actions:
        merged.actions = set(source.actions)
    if not merged.categories:
        merged.categories = set(source.categories)
    return merged


def _normalize_component_token(token: str, package_name: str = PACKAGE_NAME) -> str:
    if token.startswith(f"{package_name}/"):
        return component_class(normalize_component(token, package_name))
    return full_component_name(token, package_name)


def _new_component_boundary(line: str, tokens: set[str], package_name: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if any(token in stripped for token in tokens):
        return False
    if re.match(r"^(Activity|Service|Receiver|Provider)\s+#\d+:", stripped):
        return True
    return package_name in stripped and re.search(
        r"\b(Activity|Service|Receiver|Provider)(\{|:|\s+filter)", stripped
    )


def _component_blocks(
    package_dump: str, component_name: str, package_name: str
) -> list[str]:
    tokens = _component_tokens(component_name, package_name)
    lines = package_dump.splitlines()
    blocks: list[str] = []
    for index, line in enumerate(lines):
        if not any(token in line for token in tokens):
            continue
        end = index + 1
        for next_index in range(index + 1, min(len(lines), index + 80)):
            if _new_component_boundary(lines[next_index], tokens, package_name):
                break
            end = next_index + 1
        blocks.append("\n".join(lines[index:end]))
    return blocks


def _clean_package_value(value: str) -> str:
    value = value.strip().strip(",")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value


def parse_component_metadata(
    package_dump: str, component_name: str, package_name: str = PACKAGE_NAME
) -> PackageComponent:
    """Parse field/action/category data for one PackageManager component."""
    full_name = full_component_name(component_name, package_name)
    blocks = _component_blocks(package_dump, full_name, package_name)
    component = PackageComponent(name=full_name, present=bool(blocks), blocks=blocks)
    for block in blocks:
        for match in _COMPONENT_FIELD_RE.finditer(block):
            value = _clean_package_value(match.group("value"))
            component.fields.setdefault(match.group("field"), set()).add(value)
        for match in _QUOTED_ACTION_RE.finditer(block):
            component.actions.add(_clean_package_value(match.group("value")))
        for match in _ACT_FIELD_RE.finditer(block):
            component.actions.add(_clean_package_value(match.group("value")))
        for match in _QUOTED_CATEGORY_RE.finditer(block):
            component.categories.add(_clean_package_value(match.group("value")))
        for match in _CAT_FIELD_RE.finditer(block):
            for category in match.group("value").split(","):
                component.categories.add(_clean_package_value(category))
    return component


def component_field_values(
    component: PackageComponent, field_name: str, *, include_null: bool = False
) -> set[str]:
    """Return parsed values for a PackageManager component field."""
    values = set(component.fields.get(field_name, set()))
    if not include_null:
        values = {value for value in values if value.lower() != "null"}
    return values


def discover_components(
    package_dump: str, class_regex: str, package_name: str = PACKAGE_NAME
) -> list[str]:
    """Discover component class names in PackageManager output matching a regex."""
    pattern = re.compile(class_regex)
    token_re = re.compile(
        rf"{re.escape(package_name)}/(?:{re.escape(package_name)}\.)?"
        r"[A-Za-z0-9_.$]+"
        rf"|{re.escape(package_name)}/\.[A-Za-z0-9_.$]+"
        rf"|{re.escape(package_name)}\.[A-Za-z0-9_.$]+"
    )
    discovered = {
        _normalize_component_token(match.group(0), package_name)
        for match in token_re.finditer(package_dump)
    }
    return sorted(name for name in discovered if pattern.fullmatch(name))


def field_has_bool(
    component: PackageComponent, field_name: str, expected: bool
) -> bool:
    """Return True iff a parsed boolean field has exactly the expected value."""
    expected_text = "true" if expected else "false"
    values = {value.lower() for value in component_field_values(component, field_name)}
    return values == {expected_text}


def field_has_disabled_value(component: PackageComponent) -> bool:
    """Return True when PackageManager explicitly marks a component disabled."""
    values = {value.lower() for value in component_field_values(component, "enabled")}
    return bool(values & {"false", "0"})


def format_values(values: set[Any]) -> str:
    """Format parsed field values for diagnostics."""
    if not values:
        return "<missing>"
    return ", ".join(sorted(str(value) for value in values))


def emit_check_result(name: str, success: bool, message: str) -> dict[str, int]:
    """Print the standardized standalone check line and return JSON result."""
    prefix = "[PASS]" if success else "[FAIL]"
    print(f"{prefix} {name}: {message}", file=sys.stderr)
    return {name: 1 if success else 0}


def docker_inspect_json(container: str) -> dict[str, Any]:
    """Return Docker inspect metadata for a container.

    Raises RuntimeError if Docker is unavailable or the container cannot be
    inspected.
    """
    try:
        result = run_command(["docker", "inspect", container])
    except FileNotFoundError as exc:
        raise RuntimeError("docker command unavailable") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("docker inspect timed out") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(detail or f"docker inspect failed for {container}")
    payload = json.loads(result.stdout)
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"docker inspect returned no metadata for {container}")
    first = payload[0]
    if not isinstance(first, dict):
        raise RuntimeError(f"docker inspect metadata is malformed for {container}")
    return first


def docker_inspect(container_name: str, *, timeout: int = 10) -> dict[str, Any]:
    """Read Docker inspect metadata for one container using structured JSON."""
    try:
        return docker_inspect_json(container_name)
    except RuntimeError as exc:
        raise ProbeInfraError(str(exc)) from exc


def docker_container_running(container: str) -> bool:
    """Return True iff Docker reports the container state as running."""
    metadata = docker_inspect_json(container)
    return bool(metadata.get("State", {}).get("Running"))


def docker_port_bindings(container: str, container_port: int) -> list[dict[str, str]]:
    """Return Docker host bindings for a TCP container port."""
    metadata = docker_inspect_json(container)
    ports = metadata.get("NetworkSettings", {}).get("Ports", {})
    bindings = ports.get(f"{container_port}/tcp")
    if not bindings:
        return []
    if not isinstance(bindings, list):
        raise RuntimeError(f"unexpected Docker port binding shape for {container_port}")
    normalized: list[dict[str, str]] = []
    for binding in bindings:
        if isinstance(binding, dict):
            normalized.append(
                {
                    "HostIp": str(binding.get("HostIp", "")),
                    "HostPort": str(binding.get("HostPort", "")),
                }
            )
    return normalized


def read_tcp_banner(host: str, port: int, timeout: float = 3.0) -> SocketProbeResult:
    """Attempt a TCP connection and read an initial protocol banner if present."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            try:
                banner = sock.recv(128)
            except socket.timeout:
                banner = b""
            return SocketProbeResult(connected=True, banner=banner)
    except OSError as exc:
        return SocketProbeResult(connected=False, banner=b"", error=str(exc))


def _mqtt_remaining_length(length: int) -> bytes:
    """Encode an MQTT remaining length field."""
    encoded = bytearray()
    while True:
        digit = length % 128
        length //= 128
        if length > 0:
            digit |= 0x80
        encoded.append(digit)
        if length == 0:
            return bytes(encoded)


def mqtt_connect_anonymous(
    host: str, port: int, client_id: str, timeout: float = 5.0
) -> MqttConnack:
    """Open an MQTT 3.1.1 anonymous connection and parse the CONNACK code."""
    protocol_name = b"\x00\x04MQTT"
    variable_header = protocol_name + bytes([0x04, 0x02, 0x00, 0x3C])
    client_bytes = client_id.encode("utf-8")
    payload = len(client_bytes).to_bytes(2, "big") + client_bytes
    remaining = len(variable_header) + len(payload)
    packet = (
        bytes([0x10]) + _mqtt_remaining_length(remaining) + variable_header + payload
    )
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(packet)
            response = sock.recv(4)
    except OSError as exc:
        return MqttConnack(reached=False, return_code=None, error=str(exc))

    if len(response) < 4 or response[0] != 0x20 or response[1] != 0x02:
        return MqttConnack(
            reached=True,
            return_code=None,
            error=f"malformed CONNACK bytes: {response.hex()}",
        )
    return MqttConnack(reached=True, return_code=response[3])
