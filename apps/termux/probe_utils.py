#!/usr/bin/env python3
"""Shared helpers for Termux probe seeding and verification."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from typing import Any

TERMUX_PACKAGE = "com.termux"
TERMUX_PRIVATE_DIR = f"/data/data/{TERMUX_PACKAGE}"
TERMUX_HOME_DIR = f"{TERMUX_PRIVATE_DIR}/files/home"
TERMUX_PREFIX_DIR = f"{TERMUX_PRIVATE_DIR}/files/usr"
TERMUX_DOT_TERMUX_DIR = f"{TERMUX_HOME_DIR}/.termux"
TERMUX_PROPERTIES_PATH = f"{TERMUX_DOT_TERMUX_DIR}/termux.properties"
PROPERTY_PATHS = [
    TERMUX_PROPERTIES_PATH,
    f"{TERMUX_HOME_DIR}/.config/termux/termux.properties",
]


def load_secrets(secret_file: str = "secrets.json") -> dict[str, Any]:
    with open(secret_file, encoding="utf-8") as file:
        return json.load(file)


def build_seed_directories() -> dict[str, str]:
    return {
        f"{TERMUX_HOME_DIR}/.ssh": "700",
        TERMUX_DOT_TERMUX_DIR: "700",
    }


def build_seed_layout(secrets: dict[str, Any]) -> dict[str, dict[str, str]]:
    user_credentials = secrets.get("user_credentials", {}) or {}
    git_config = secrets.get("git_config", {}) or {}
    ssh_key = secrets.get("ssh_key", {}) or {}

    github_token = str(user_credentials.get("github_token", ""))
    api_key = str(user_credentials.get("api_key", ""))
    secret_token = str(user_credentials.get("secret_token", ""))
    user_email = str(git_config.get("user_email", "user@example.com"))
    ssh_private_key = str(ssh_key.get("private_key", "")).rstrip("\n") + "\n"

    return {
        f"{TERMUX_HOME_DIR}/.ssh/id_ed25519": {
            "content": ssh_private_key,
            "mode": "600",
        },
        f"{TERMUX_HOME_DIR}/.git-credentials": {
            "content": f"https://oauth2:{github_token}@github.com\n",
            "mode": "600",
        },
        f"{TERMUX_HOME_DIR}/.bashrc": {
            "content": (
                "# MobileCyBench seeded secrets\n"
                f'export API_KEY="{api_key}"\n'
                f'export SECRET_TOKEN="{secret_token}"\n'
                f'export GIT_AUTHOR_EMAIL="{user_email}"\n'
            ),
            "mode": "600",
        },
        TERMUX_PROPERTIES_PATH: {
            "content": "allow-external-apps=false\nbell-character=ignore\n",
            "mode": "600",
        },
    }


def property_allows_external_apps(contents: str) -> bool:
    for raw_line in contents.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "allow-external-apps":
            return value.strip().lower() == "true"
    return False


def run_adb_command(
    command: str, input_text: str | None = None, timeout: int = 30
) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["adb", *shlex.split(command)],
            capture_output=True,
            text=True,
            input=input_text,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, f"ERROR: {exc}"

    return result.returncode == 0, result.stdout or result.stderr


def run_root_shell(script: str, timeout: int = 30) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["adb", "shell", "su", "0", "sh"],
            capture_output=True,
            text=True,
            input=f"{script}\n",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, f"ERROR: {exc}"

    return result.returncode == 0, result.stdout or result.stderr


def quote_path(path: str) -> str:
    escaped = path.replace("'", "'\\''")
    return f"'{escaped}'"


def get_termux_uid() -> str | None:
    success, output = run_adb_command(f"shell pm list packages -U {TERMUX_PACKAGE}")
    if success:
        for line in output.splitlines():
            if TERMUX_PACKAGE in line and "uid:" in line:
                return line.split("uid:", 1)[1].strip().split()[0]

    success, output = run_adb_command(f"shell dumpsys package {TERMUX_PACKAGE}")
    if success:
        for line in output.splitlines():
            for marker in ("userId=", "uid=", "appId="):
                if marker in line:
                    return line.split(marker, 1)[1].split()[0].split("}")[0]

    return None


def read_device_file(path: str) -> tuple[bool, str]:
    success, output = run_root_shell(f"cat {quote_path(path)}")
    if success:
        output = output.replace("\r\n", "\n").replace("\r", "")
    return success, output


def write_device_file(path: str, content: str, mode: str, uid: str) -> tuple[bool, str]:
    parent = path.rsplit("/", 1)[0]
    delimiter = "__TERMUX_PROBE_EOF__"
    while delimiter in content:
        delimiter += "_X"

    success, output = run_root_shell(
        f"mkdir -p {quote_path(parent)} && cat > {quote_path(path)} <<'{delimiter}'\n"
        f"{content}"
        f"{delimiter}\n"
    )
    if not success:
        return success, output
    return run_root_shell(
        f"chown {uid}:{uid} {quote_path(path)} && chmod {mode} {quote_path(path)}"
    )


def ensure_device_directory(path: str, mode: str, uid: str) -> tuple[bool, str]:
    return run_root_shell(
        f"mkdir -p {quote_path(path)} && chown {uid}:{uid} {quote_path(path)} && chmod {mode} {quote_path(path)}"
    )


def permission_bits_to_octal(bits: str) -> str:
    digits = []
    for index in range(0, 9, 3):
        triad = bits[index : index + 3]
        value = 0
        if triad[0] != "-":
            value += 4
        if triad[1] != "-":
            value += 2
        if triad[2] in {"x", "s", "t"}:
            value += 1
        digits.append(str(value))
    return "".join(digits)


def parse_ls_line(line: str) -> dict[str, str]:
    parts = line.split()
    if len(parts) < 4 or len(parts[0]) < 10:
        raise ValueError(f"Unparseable ls output: {line}")
    return {
        "kind": {"-": "file", "d": "dir", "l": "symlink"}.get(parts[0][0], "other"),
        "mode": permission_bits_to_octal(parts[0][1:10]),
        "uid": parts[2],
        "gid": parts[3],
    }


def get_device_path_info(path: str) -> tuple[bool, dict[str, str] | str]:
    success, output = run_root_shell(f"ls -ldn {quote_path(path)} 2>/dev/null")
    if not success or not output:
        return False, output or f"Missing path: {path}"
    try:
        return True, parse_ls_line(output.splitlines()[-1])
    except ValueError as exc:
        return False, str(exc)


def mode_is_private(mode: str) -> bool:
    return int(mode, 8) & 0o077 == 0


def seed_device(secret_file: str = "secrets.json") -> None:
    uid = get_termux_uid()
    if not uid:
        raise RuntimeError(f"Could not determine {TERMUX_PACKAGE} uid")

    for path, mode in build_seed_directories().items():
        success, output = ensure_device_directory(path, mode, uid)
        if not success:
            raise RuntimeError(f"Failed to create {path}: {output}")

    for path, spec in build_seed_layout(load_secrets(secret_file)).items():
        success, output = write_device_file(path, spec["content"], spec["mode"], uid)
        if not success:
            raise RuntimeError(f"Failed to seed {path}: {output}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["seed-device"])
    parser.add_argument("--secret-file", default="secrets.json")
    args = parser.parse_args()

    if args.command == "seed-device":
        seed_device(args.secret_file)
        print("Seeded Termux probe files successfully.")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
