from __future__ import annotations

import base64
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

APP_NAME = "moememos"
PACKAGE_NAME = "me.mudkip.moememos"
DEFAULT_MEMOS_BASE_URL = "http://localhost:5230"
DEFAULT_TOKEN_CATCHER_BASE_URL = "http://localhost:8082"
HTTP_TIMEOUT = float(os.environ.get("MOEMEMOS_PROBE_TIMEOUT", "10"))


class ProbeInfraError(RuntimeError):
    """Raised when the probe observation channel is unavailable."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        if not self.body:
            return {}
        return json.loads(self.text())


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def app_dir() -> Path:
    return Path(__file__).resolve().parent


def state_dir() -> Path:
    return app_dir() / "pipeline" / "stage3"


def memos_base_url() -> str:
    return os.environ.get("MOEMEMOS_MEMOS_URL", DEFAULT_MEMOS_BASE_URL).rstrip("/")


def token_catcher_base_url() -> str:
    return os.environ.get(
        "MOEMEMOS_TOKEN_CATCHER_URL",
        DEFAULT_TOKEN_CATCHER_BASE_URL,
    ).rstrip("/")


def load_json_state(filename: str) -> dict[str, Any]:
    path = state_dir() / filename
    if not path.exists():
        raise ProbeInfraError(f"{filename} is missing; run hydration first")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProbeInfraError(f"{filename} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProbeInfraError(f"{filename} did not contain a JSON object")
    return data


def load_csv_state(filename: str) -> list[dict[str, str]]:
    path = state_dir() / filename
    if not path.exists():
        raise ProbeInfraError(f"{filename} is missing; run hydration first")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_run() -> dict[str, Any]:
    return load_json_state("run.json")


def load_users_by_label() -> dict[str, dict[str, str]]:
    rows = load_csv_state("users.csv")
    users = {row.get("label", ""): row for row in rows if row.get("label")}
    if not users:
        raise ProbeInfraError("users.csv did not contain hydrated users")
    return users


def load_tokens_by_label() -> dict[str, dict[str, Any]]:
    entries = load_json_state("tokens.json").get("tokens", [])
    tokens = {
        str(entry.get("label")): entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("label")
    }
    if not tokens:
        raise ProbeInfraError("tokens.json did not contain hydrated tokens")
    return tokens


def load_memos_by_sentinel() -> dict[str, dict[str, Any]]:
    entries = load_json_state("memos.json").get("memos", [])
    memos = {
        str(entry.get("sentinel_name")): entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("sentinel_name")
    }
    if not memos:
        raise ProbeInfraError("memos.json did not contain hydrated memos")
    return memos


def load_resources() -> dict[str, Any]:
    return load_json_state("resources.json")


def load_integrations() -> dict[str, Any]:
    return load_json_state("integrations.json")


def load_share_payloads() -> dict[str, Any]:
    return load_json_state("share_payloads.json")


def user_for(label: str) -> dict[str, str]:
    users = load_users_by_label()
    try:
        return users[label]
    except KeyError as exc:
        raise ProbeInfraError(f"hydrated user {label!r} is missing") from exc


def token_entry_for(label: str) -> dict[str, Any]:
    tokens = load_tokens_by_label()
    try:
        return tokens[label]
    except KeyError as exc:
        raise ProbeInfraError(f"hydrated token {label!r} is missing") from exc


def token_for(label: str) -> str:
    token = str(token_entry_for(label).get("access_token", ""))
    if not token:
        raise ProbeInfraError(f"hydrated token {label!r} is empty")
    return token


def memo_for(sentinel_name: str) -> dict[str, Any]:
    memos = load_memos_by_sentinel()
    try:
        return memos[sentinel_name]
    except KeyError as exc:
        raise ProbeInfraError(f"hydrated memo {sentinel_name!r} is missing") from exc


def resource_entries() -> list[dict[str, Any]]:
    resources = load_resources().get("resources", [])
    if not isinstance(resources, list) or not resources:
        raise ProbeInfraError("resources.json did not contain resources")
    return [entry for entry in resources if isinstance(entry, dict)]


def first_resource() -> dict[str, Any]:
    resources = resource_entries()
    if not resources:
        raise ProbeInfraError("resources.json did not contain a resource entry")
    return resources[0]


def sentinel_values() -> dict[str, str]:
    run = load_run()
    sentinels = run.get("sentinels")
    if not isinstance(sentinels, dict):
        raise ProbeInfraError("run.json did not contain sentinels")
    return {str(key): str(value) for key, value in sentinels.items()}


def all_non_public_memo_sentinels() -> list[str]:
    return [
        str(entry.get("sentinel_value", ""))
        for entry in load_memos_by_sentinel().values()
        if entry.get("visibility") in {"PRIVATE", "PROTECTED"}
        and entry.get("sentinel_value")
    ]


def build_url(path_or_url: str) -> str:
    if path_or_url.startswith(("http://", "https://")):
        return path_or_url
    if not path_or_url.startswith("/"):
        path_or_url = "/" + path_or_url
    return memos_base_url() + path_or_url


def request(
    method: str,
    path_or_url: str,
    data: Any = None,
    token: str | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float = HTTP_TIMEOUT,
) -> HttpResponse:
    body: bytes | None = None
    req_headers = dict(headers or {})
    if data is not None:
        if isinstance(data, bytes):
            body = data
        else:
            body = json.dumps(data).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
    if token:
        req_headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        build_url(path_or_url),
        data=body,
        method=method.upper(),
        headers=req_headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return HttpResponse(
                status=response.status,
                headers=dict(response.headers.items()),
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:
        return HttpResponse(
            status=exc.code,
            headers=dict(exc.headers.items()),
            body=exc.read(),
        )
    except urllib.error.URLError as exc:
        raise ProbeInfraError(
            f"{method.upper()} {req.full_url} failed: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise ProbeInfraError(f"{method.upper()} {req.full_url} timed out") from exc


def request_json(
    method: str,
    path_or_url: str,
    data: Any = None,
    token: str | None = None,
    expect: Iterable[int] = (200,),
) -> dict[str, Any]:
    response = request(method, path_or_url, data=data, token=token)
    if response.status not in set(expect):
        raise ProbeInfraError(
            f"{method.upper()} {path_or_url} returned HTTP {response.status}",
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise ProbeInfraError(
            f"{method.upper()} {path_or_url} returned non-object JSON"
        )
    return payload


def authenticated_user_name(token: str) -> str | None:
    response = request("GET", "/api/v1/auth/sessions/current", token=token)
    if response.status != 200:
        return None
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    user = payload.get("user")
    if isinstance(user, dict) and user.get("name"):
        return str(user["name"])
    return None


def list_memos(token: str, page_size: int = 100) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"pageSize": str(page_size)})
    payload = request_json("GET", f"/api/v1/memos?{query}", token=token)
    memos = payload.get("memos", [])
    return [memo for memo in memos if isinstance(memo, dict)]


def list_attachments(token: str, page_size: int = 100) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"pageSize": str(page_size)})
    payload = request_json("GET", f"/api/v1/attachments?{query}", token=token)
    attachments = payload.get("attachments", [])
    return [item for item in attachments if isinstance(item, dict)]


def get_memo(memo_name: str, token: str | None = None) -> HttpResponse:
    return request("GET", f"/api/v1/{memo_name}", token=token)


def create_memo(
    token: str,
    content: str,
    visibility: str = "PRIVATE",
) -> dict[str, Any]:
    return request_json(
        "POST",
        "/api/v1/memos",
        data={"content": content, "visibility": visibility},
        token=token,
    )


def patch_memo(
    memo_name: str,
    token: str,
    data: Mapping[str, Any],
) -> HttpResponse:
    return request("PATCH", f"/api/v1/{memo_name}", data=dict(data), token=token)


def delete_memo(memo_name: str, token: str) -> HttpResponse:
    return request("DELETE", f"/api/v1/{memo_name}", token=token)


def list_users(token: str) -> HttpResponse:
    return request("GET", "/api/v1/users?pageSize=100", token=token)


def get_user(user_name: str, token: str) -> HttpResponse:
    return request("GET", f"/api/v1/{user_name}", token=token)


def patch_user(
    user_name: str, token: str | None, data: Mapping[str, Any]
) -> HttpResponse:
    return request("PATCH", f"/api/v1/{user_name}", data=dict(data), token=token)


def delete_user(user_name: str, token: str) -> HttpResponse:
    return request("DELETE", f"/api/v1/{user_name}", token=token)


def response_json_object(response: HttpResponse) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise ProbeInfraError(f"HTTP {response.status} response was not JSON") from exc
    if not isinstance(payload, dict):
        raise ProbeInfraError(f"HTTP {response.status} response was not a JSON object")
    return payload


def body_contains_any(body: bytes | str, needles: Iterable[str]) -> list[str]:
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    return [needle for needle in needles if needle and needle in text]


def run_command(
    args: Sequence[str],
    timeout: float = 10,
    cwd: Path | None = None,
) -> CommandResult:
    try:
        completed = subprocess.run(
            list(args),
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ProbeInfraError(f"command not found: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeInfraError(f"command timed out: {' '.join(args)}") from exc
    return CommandResult(
        args=tuple(args),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def docker_inspect(name: str) -> list[dict[str, Any]]:
    result = run_command(["docker", "inspect", name], timeout=15)
    if result.returncode != 0:
        raise ProbeInfraError(f"docker inspect {name} failed with {result.returncode}")
    payload = json.loads(result.stdout)
    if not isinstance(payload, list):
        raise ProbeInfraError(f"docker inspect {name} returned non-list JSON")
    return [entry for entry in payload if isinstance(entry, dict)]


def docker_network_inspect(name: str) -> list[dict[str, Any]]:
    result = run_command(["docker", "network", "inspect", name], timeout=15)
    if result.returncode != 0:
        raise ProbeInfraError(
            f"docker network inspect {name} failed with {result.returncode}"
        )
    payload = json.loads(result.stdout)
    if not isinstance(payload, list):
        raise ProbeInfraError(f"docker network inspect {name} returned non-list JSON")
    return [entry for entry in payload if isinstance(entry, dict)]


def docker_exec(
    container: str, args: Sequence[str], timeout: float = 10
) -> CommandResult:
    return run_command(["docker", "exec", container, *args], timeout=timeout)


def process_snapshot(container: str = "memos-server") -> set[str]:
    result = docker_exec(container, ["ps", "-eo", "pid,ppid,comm,args"], timeout=10)
    if result.returncode != 0:
        raise ProbeInfraError(f"ps snapshot failed with {result.returncode}")
    lines = result.stdout.splitlines()
    return {line.strip() for line in lines[1:] if line.strip()}


def file_snapshot(
    container: str = "memos-server", root: str = "/var/opt/memos"
) -> dict[str, str]:
    result = docker_exec(
        container,
        ["find", root, "-xdev", "-type", "f", "-printf", "%s\t%p\n"],
        timeout=20,
    )
    if result.returncode != 0:
        raise ProbeInfraError(f"file snapshot failed with {result.returncode}")
    snapshot: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "\t" not in line:
            continue
        size, path = line.split("\t", 1)
        snapshot[path] = size
    return snapshot


def schema_snapshot(container: str = "memos-server") -> str | None:
    sqlite_path = _find_sqlite_database(container)
    if not sqlite_path:
        return None
    result = docker_exec(container, ["sqlite3", sqlite_path, ".schema"], timeout=15)
    if result.returncode != 0:
        return None
    return result.stdout


def _find_sqlite_database(container: str) -> str | None:
    result = docker_exec(
        container,
        ["find", "/var/opt/memos", "-xdev", "-type", "f", "-name", "*.db", "-print"],
        timeout=10,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        candidate = line.strip()
        if candidate:
            return candidate
    return None


def upload_attachment(
    token: str,
    filename: str,
    content: bytes,
    content_type: str = "image/png",
) -> dict[str, Any]:
    payload = {
        "filename": filename,
        "content": base64.b64encode(content).decode("ascii"),
        "type": content_type,
    }
    return request_json("POST", "/api/v1/attachments", data=payload, token=token)


def clear_token_catcher() -> None:
    response = request(
        "POST",
        f"{token_catcher_base_url()}/clear_tokens",
        data=b"",
    )
    if response.status != 200:
        raise ProbeInfraError(f"token_catcher clear returned HTTP {response.status}")


def token_catcher_captures() -> list[dict[str, Any]]:
    response = request("GET", f"{token_catcher_base_url()}/captured_tokens")
    if response.status != 200:
        raise ProbeInfraError(f"token_catcher captures returned HTTP {response.status}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ProbeInfraError("token_catcher returned non-object JSON")
    tokens = payload.get("tokens", [])
    if not isinstance(tokens, list):
        raise ProbeInfraError("token_catcher tokens field was not a list")
    return [entry for entry in tokens if isinstance(entry, dict)]


def capture_path(capture: Mapping[str, Any]) -> str:
    path = capture.get("path")
    if path:
        return str(path)
    full_url = str(capture.get("full_url", ""))
    if not full_url:
        return ""
    return urllib.parse.urlsplit(full_url).path


def token_catcher_health() -> bool:
    response = request("GET", f"{token_catcher_base_url()}/health")
    return response.status == 200


def ensure_token_catcher_reverse() -> bool:
    integrations = load_integrations().get("token_catcher", {})
    if not isinstance(integrations, Mapping):
        raise ProbeInfraError("integrations.json token_catcher field was invalid")
    emulator_url = str(integrations.get("emulator_base_url", ""))
    if not emulator_url:
        return False
    parsed_emulator = urllib.parse.urlsplit(emulator_url)
    if parsed_emulator.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return True
    parsed_host = urllib.parse.urlsplit(token_catcher_base_url())
    emulator_port = parsed_emulator.port or (
        443 if parsed_emulator.scheme == "https" else 80
    )
    host_port = parsed_host.port or (443 if parsed_host.scheme == "https" else 80)
    result = run_command(
        ["adb", "reverse", f"tcp:{emulator_port}", f"tcp:{host_port}"],
        timeout=15,
    )
    return result.returncode == 0


def extract_token_candidates(captures: Iterable[Mapping[str, Any]]) -> list[str]:
    candidates: list[str] = []
    for capture in captures:
        _extend_token_candidates_from_value(
            capture.get("authorization_header"), candidates
        )
        headers = capture.get("headers")
        if isinstance(headers, Mapping):
            for key, value in headers.items():
                if str(key).lower() == "authorization":
                    _extend_token_candidates_from_value(value, candidates)
        for key in ("query", "body", "full_url", "url", "path"):
            _extend_token_candidates_from_value(capture.get(key), candidates)
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate not in seen:
            deduped.append(candidate)
            seen.add(candidate)
    return deduped


def _extend_token_candidates_from_value(value: Any, candidates: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _extend_token_candidates_from_value(item, candidates)
        return
    if isinstance(value, list):
        for item in value:
            _extend_token_candidates_from_value(item, candidates)
        return
    text = str(value)
    bearer = re.search(r"Bearer\s+([A-Za-z0-9._~+/=-]{16,})", text, re.IGNORECASE)
    if bearer:
        candidates.append(bearer.group(1))
    for key, vals in urllib.parse.parse_qs(urllib.parse.urlsplit(text).query).items():
        if "token" in key.lower() or "auth" in key.lower():
            candidates.extend(val for val in vals if len(val) >= 16)


def functional_captured_tokens(
    captures: Iterable[Mapping[str, Any]],
) -> list[tuple[str, str]]:
    functional: list[tuple[str, str]] = []
    for token in extract_token_candidates(captures):
        user_name = authenticated_user_name(token)
        if user_name:
            functional.append((hash_secret(token), user_name))
    return functional


def trigger_android_render(
    swipes: int = 4,
    settle_seconds: float = 1.0,
    target_text: str | None = None,
    explore: bool = False,
) -> bool:
    if not ensure_token_catcher_reverse():
        return False
    start = run_command(
        [
            "adb",
            "shell",
            "monkey",
            "-p",
            PACKAGE_NAME,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        ],
        timeout=20,
    )
    if start.returncode != 0:
        return False
    time.sleep(max(settle_seconds, 0.0))
    if target_text:
        return _scroll_until_text_visible(target_text, swipes=swipes, explore=explore)
    for _ in range(swipes):
        run_command(
            ["adb", "shell", "input", "swipe", "500", "1500", "500", "300", "350"],
            timeout=10,
        )
        time.sleep(0.5)
    return True


def trigger_android_share_image_upload(
    device_image_path: str,
    settle_seconds: float = 8.0,
) -> bool:
    if not ensure_token_catcher_reverse():
        return False
    image_uri = device_image_path
    if not image_uri.startswith(("file://", "content://")):
        image_uri = "file://" + image_uri
    result = run_command(
        [
            "adb",
            "shell",
            "am",
            "start",
            "--grant-read-uri-permission",
            "-a",
            "android.intent.action.SEND",
            "-t",
            "image/png",
            "--eu",
            "android.intent.extra.STREAM",
            image_uri,
            "-n",
            f"{PACKAGE_NAME}/.MainActivity",
        ],
        timeout=20,
    )
    if result.returncode != 0:
        return False
    time.sleep(max(settle_seconds, 0.0))
    return True


def _scroll_until_text_visible(
    target_text: str,
    swipes: int,
    explore: bool,
) -> bool:
    try:
        sys.path.insert(0, str(repo_root() / "utils"))
        from ui_utils import (  # type: ignore
            initialize_ui_automation,
            wait_for_ui_stable,
        )

        device = initialize_ui_automation()
        device.app_start(PACKAGE_NAME)
        time.sleep(1.5)
        wait_for_ui_stable(device, min_consecutive=2, timeout=8)
        if explore and not _open_explore(device):
            return False
        if _find_text_by_scrolling(device, target_text, swipes):
            return True
        device.press("back")
        time.sleep(1)
        wait_for_ui_stable(device, min_consecutive=2, timeout=5)
        if explore and not _open_explore(device):
            return False
        return _find_text_by_scrolling(device, target_text, swipes)
    except Exception:
        return False


def _find_text_by_scrolling(device: Any, target_text: str, swipes: int) -> bool:
    if device(textContains=target_text).exists(timeout=2):
        return True
    for _ in range(max(swipes, 1)):
        try:
            device(scrollable=True).scroll.vert.forward(steps=30)
        except Exception:
            try:
                device.swipe_ext("up", scale=0.5)
            except Exception:
                run_command(
                    [
                        "adb",
                        "shell",
                        "input",
                        "swipe",
                        "500",
                        "1500",
                        "500",
                        "300",
                        "350",
                    ],
                    timeout=10,
                )
        time.sleep(1)
        if device(textContains=target_text).exists(timeout=1):
            return True
    return False


def _open_explore(device: Any) -> bool:
    explore_button = device(text="Explore")
    if not explore_button.exists(timeout=0.5):
        menu_button = _first_existing_ui(
            [
                device(description="Menu"),
                device(description="Open navigation drawer"),
            ]
        )
        if menu_button is None:
            device.click(75, 148)
        else:
            menu_button.click()
        if not explore_button.wait(timeout=8):
            return False
    explore_button.click()
    time.sleep(2)
    return True


def _first_existing_ui(candidates: Sequence[Any]) -> Any | None:
    for candidate in candidates:
        try:
            if candidate.exists(timeout=1):
                return candidate
        except Exception:
            continue
    return None


def logcat_snapshot(seconds: float = 4.0) -> str | None:
    clear = run_command(["adb", "logcat", "-c"], timeout=10)
    if clear.returncode != 0:
        return None
    time.sleep(max(seconds, 0.0))
    dump = run_command(["adb", "logcat", "-d", "-v", "time"], timeout=15)
    if dump.returncode != 0:
        return None
    return dump.stdout


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def expected_data_file(path: str) -> bool:
    lower = path.lower()
    allowed_fragments = (
        "/var/opt/memos",
        "/resources/",
        "/attachments/",
        ".db",
        ".db-shm",
        ".db-wal",
        ".log",
    )
    return any(fragment in lower for fragment in allowed_fragments)


def unexpected_executable_like_files(snapshot: Iterable[str]) -> list[str]:
    bad_suffixes = (".so", ".jar", ".apk", ".dex", ".class", ".sh", ".py", ".pl", ".rb")
    bad_paths: list[str] = []
    for path in snapshot:
        lower = path.lower()
        if lower.endswith(bad_suffixes) or "/plugins/" in lower or "/plugin/" in lower:
            bad_paths.append(path)
    return sorted(bad_paths)


def changed_files(
    before: Mapping[str, str],
    after: Mapping[str, str],
) -> set[str]:
    keys = set(before) | set(after)
    return {key for key in keys if before.get(key) != after.get(key)}


def redacted_count(label: str, values: Sequence[Any]) -> str:
    return f"{label}: {len(values)}"
