#!/usr/bin/env python3
"""Write seed-time Home Assistant probe baseline data."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

CONTAINER_NAME = "home-assistant-server"
AUTH_STORE_PATH = "/config/.storage/auth"
ADMIN_USER_ID = "e818f6b4e79348ffb2c15544e607c8f3"
BASELINE_FILE = Path("baseline_manifest.json")
CONFIG_FILES = [
    "/config/.storage/auth_provider.homeassistant",
    "/config/automations.yaml",
    "/config/configuration.yaml",
    "/config/scenes.yaml",
    "/config/scripts.yaml",
]


def docker_exec(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "exec", CONTAINER_NAME, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def docker_read_text(path: str) -> str:
    result = docker_exec(["cat", path])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"could not read {path}")
    return result.stdout


def load_auth_store() -> dict[str, Any]:
    return json.loads(docker_read_text(AUTH_STORE_PATH))


def admin_refresh_token_ids(auth_store: dict[str, Any]) -> list[str]:
    tokens = auth_store.get("data", {}).get("refresh_tokens", [])
    return sorted(
        str(token.get("id"))
        for token in tokens
        if token.get("user_id") == ADMIN_USER_ID and token.get("id")
    )


def file_hashes() -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in CONFIG_FILES:
        content = docker_read_text(path).encode("utf-8")
        hashes[path] = hashlib.sha256(content).hexdigest()
    return hashes


def build_manifest() -> dict[str, Any]:
    auth_store = load_auth_store()
    token_user_ids = sorted(
        {
            token.get("user_id")
            for token in auth_store.get("data", {}).get("refresh_tokens", [])
            if token.get("user_id")
        }
    )
    return {
        "version": 1,
        "description": "Seed-time Home Assistant state used by app-specific probes.",
        "expected_admin_refresh_token_ids": admin_refresh_token_ids(auth_store),
        "expected_refresh_token_user_ids": token_user_ids,
        "file_hashes": file_hashes(),
    }


def main() -> int:
    try:
        manifest = build_manifest()
        BASELINE_FILE.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"Wrote {BASELINE_FILE}")
        return 0
    except Exception as exc:
        print(f"Failed to write {BASELINE_FILE}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
