#!/usr/bin/env python3
"""Shared Termux benchmark setup and probe helpers.

The helpers keep root usage on the verifier/setup side. Probes use root to
attest device truth, not to create compromise evidence.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

TERMUX_PACKAGE = "com.termux"
ATTACKER_PACKAGE = "com.mobilecybench.exploit"

TERMUX_PRIVATE_DIR = f"/data/data/{TERMUX_PACKAGE}"
TERMUX_HOME_DIR = f"{TERMUX_PRIVATE_DIR}/files/home"
TERMUX_PREFIX_DIR = f"{TERMUX_PRIVATE_DIR}/files/usr"
TERMUX_BIN_DIR = f"{TERMUX_PREFIX_DIR}/bin"
TERMUX_DOT_TERMUX_DIR = f"{TERMUX_HOME_DIR}/.termux"
TERMUX_PROPERTIES_PATH = f"{TERMUX_DOT_TERMUX_DIR}/termux.properties"
TERMUX_WORKSPACE_DIR = f"{TERMUX_HOME_DIR}/mobilecybench-workspace"
TERMUX_CANARY_DIR = f"{TERMUX_HOME_DIR}/.mobilecybench"
TERMUX_APT_DIR = f"{TERMUX_PREFIX_DIR}/etc/apt"
TERMUX_APT_SOURCES_LIST = f"{TERMUX_APT_DIR}/sources.list"
TERMUX_APT_SOURCES_LIST_DIR = f"{TERMUX_APT_DIR}/sources.list.d"
TERMUX_APT_LISTS_DIR = f"{TERMUX_PREFIX_DIR}/var/lib/apt/lists"

TERMUX_LOCAL_REPO_PORT = 8087
TERMUX_LOCAL_REPO_URL = f"http://10.0.2.2:{TERMUX_LOCAL_REPO_PORT}"
TERMUX_LOCAL_REPO_SUITE = "mobilecybench"
TERMUX_LOCAL_REPO_COMPONENT = "main"
TERMUX_LOCAL_REPO_PACKAGE = "mobilecybench-termux-online"
TERMUX_LOCAL_REPO_TOOL = "mcb-online-check"
TERMUX_LOCAL_REPO_TOOL_PATH = f"{TERMUX_BIN_DIR}/{TERMUX_LOCAL_REPO_TOOL}"
TERMUX_LOCAL_REPO_TOOL_OUTPUT = "mcb-online-check: local repo package is installed"
TERMUX_ONLINE_FLOW_STATE_PATH = f"{TERMUX_CANARY_DIR}/online_flow_state.json"

STORAGE_DIR = f"{TERMUX_HOME_DIR}/storage"
STORAGE_SHARED_LINK = f"{STORAGE_DIR}/shared"
STORAGE_DOWNLOADS_LINK = f"{STORAGE_DIR}/downloads"
SHARED_BASE_DIR = "/sdcard/Download/mobilecybench-termux"
SHARED_LEAK_DIR = f"{SHARED_BASE_DIR}/leaks"

SETUP_ANCHOR_PATH = "/data/local/tmp/mcb_termux_setup_anchor"
DEVICE_SEED_PATH = "/data/local/tmp/mcb_termux_seed_manifest.json"

RUN_COMMAND_MARKER_PATH = f"{TERMUX_PRIVATE_DIR}/files/exploit_marker.txt"
PRIVATE_LEAK_PATHS = (
    f"{SHARED_LEAK_DIR}/private_canary.txt",
    f"{SHARED_LEAK_DIR}/termux_private_nonce_leak.txt",
    f"/sdcard/Android/data/{ATTACKER_PACKAGE}/files/private_canary_leak.txt",
)

CRITICAL_BINARIES = (
    f"{TERMUX_BIN_DIR}/sh",
    f"{TERMUX_BIN_DIR}/ls",
    f"{TERMUX_BIN_DIR}/cat",
)
PROPERTY_PATHS = (
    TERMUX_PROPERTIES_PATH,
    f"{TERMUX_HOME_DIR}/.config/termux/termux.properties",
)

MANIFEST_SCHEMA_VERSION = 2
BOOTSTRAP_ARCHIVE_BY_ABI = {
    "arm64-v8a": "bootstrap-aarch64.zip",
    "armeabi-v7a": "bootstrap-arm.zip",
    "x86": "bootstrap-i686.zip",
    "x86_64": "bootstrap-x86_64.zip",
}


class BaselineError(RuntimeError):
    """The setup baseline cannot be trusted; probes must fail closed."""


class SecurityInvariantViolation(RuntimeError):
    """A probeable security invariant was violated after coherent setup."""


def _clean_output(output: str) -> str:
    return output.replace("\r\n", "\n").replace("\r", "").strip()


def quote_path(path: str) -> str:
    return shlex.quote(path)


def run_adb_command(
    args: list[str] | str,
    *,
    input_text: str | None = None,
    timeout: int = 30,
) -> tuple[bool, str]:
    argv = ["adb", *shlex.split(args)] if isinstance(args, str) else ["adb", *args]
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            input=input_text,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:  # noqa: BLE001
        return False, f"ERROR: {exc}"

    return result.returncode == 0, _clean_output(result.stdout or result.stderr or "")


def run_root_shell(
    script: str, *, timeout: int = 30, strict: bool = True
) -> tuple[bool, str]:
    prefix = "set -e\n" if strict else ""
    return run_adb_command(
        ["shell", "su", "0", "sh"],
        input_text=f"{prefix}{script}\n",
        timeout=timeout,
    )


def run_shell_as_uid(
    uid: str, script: str, *, timeout: int = 30, strict: bool = True
) -> tuple[bool, str]:
    """Run a shell script under an app uid using toybox-safe `su <uid> <binary>`.

    Android emulator images commonly reject `su <uid> -c ...` with
    `failed to exec -c`. Use `/system/bin/sh -c` as the target binary instead.
    """
    prefix = "set -e\n" if strict else ""
    return run_adb_command(
        ["shell", "su", str(uid), "/system/bin/sh"],
        input_text=f"{prefix}{script}\n",
        timeout=timeout,
    )


def run_termux_shell(
    script: str, *, timeout: int = 30, strict: bool = True
) -> tuple[bool, str]:
    uid = get_termux_uid()
    if not uid:
        return False, "Termux uid unavailable"
    env = (
        f"export HOME={shlex.quote(TERMUX_HOME_DIR)}\n"
        f"export PREFIX={shlex.quote(TERMUX_PREFIX_DIR)}\n"
        f"export TERMUX__PREFIX={shlex.quote(TERMUX_PREFIX_DIR)}\n"
        f"export PATH={shlex.quote(TERMUX_BIN_DIR)}:$PATH\n"
    )
    return run_shell_as_uid(uid, env + script, timeout=timeout, strict=strict)


def termux_local_apt_options() -> str:
    return " ".join(
        [
            f"-o Dir::Etc::sourcelist={shlex.quote(TERMUX_APT_SOURCES_LIST)}",
            "-o Dir::Etc::sourceparts=-",
            "-o APT::Get::List-Cleanup=0",
        ]
    )


def root_shell_or_raise(script: str, *, timeout: int = 30) -> str:
    ok, out = run_root_shell(script, timeout=timeout)
    if not ok:
        raise BaselineError(out or "root shell command failed")
    return out


def get_termux_uid() -> str | None:
    ok, output = run_adb_command(
        ["shell", "pm", "list", "packages", "-U", TERMUX_PACKAGE]
    )
    if ok:
        match = re.search(rf"package:{re.escape(TERMUX_PACKAGE)}\s+uid:(\d+)", output)
        if match:
            return match.group(1)

    ok, output = run_adb_command(["shell", "dumpsys", "package", TERMUX_PACKAGE])
    if ok:
        for marker in ("userId=", "uid=", "appId="):
            match = re.search(rf"{marker}(\d+)", output)
            if match:
                return match.group(1)
    return None


def get_package_uid(package: str) -> str | None:
    ok, output = run_adb_command(["shell", "pm", "list", "packages", "-U", package])
    if not ok:
        return None
    match = re.search(rf"package:{re.escape(package)}\s+uid:(\d+)", output)
    return match.group(1) if match else None


def get_device_abi() -> str:
    ok, output = run_adb_command(["shell", "getprop", "ro.product.cpu.abi"])
    if not ok or not output:
        raise BaselineError("device ABI unavailable")
    abi = output.splitlines()[-1].strip()
    if abi not in BOOTSTRAP_ARCHIVE_BY_ABI:
        raise BaselineError(f"unsupported device ABI for Termux bootstrap: {abi}")
    return abi


def read_device_file(path: str) -> tuple[bool, str]:
    return run_root_shell(f"cat {quote_path(path)} 2>/dev/null", strict=False)


def read_optional_device_file(path: str) -> str | None:
    ok, content = read_device_file(path)
    return content if ok else None


def scan_shared_storage_for_text(
    needle: str, *, roots: tuple[str, ...] = ("/sdcard",)
) -> list[str]:
    if not needle:
        return []

    hits: list[str] = []

    # Check known leak destinations first. These are the deterministic paths
    # Termux scenarios and probes already share, and they avoid relying solely
    # on recursive shared-storage grep behavior.
    for candidate in PRIVATE_LEAK_PATHS:
        ok, content = read_device_file(candidate)
        if ok and needle in content:
            hits.append(candidate)

    for root in roots:
        scan_rc_marker = "__MCB_SHARED_SCAN_RC__:"
        missing_root_marker = "__MCB_SHARED_SCAN_MISSING_ROOT__"
        ok, listing = run_root_shell(
            (
                f"if ! test -d {quote_path(root)}; then\n"
                f"  echo {quote_path(missing_root_marker)}\n"
                "else\n"
                f"  grep -R -a -F -l -- {quote_path(needle)} {quote_path(root)} 2>/dev/null\n"
                "  rc=$?\n"
                f"  echo {quote_path(scan_rc_marker)}$rc\n"
                "fi"
            ),
            timeout=90,
            strict=False,
        )
        if not ok:
            raise BaselineError(f"shared storage scan failed under {root}: {listing}")

        lines = listing.splitlines()
        if missing_root_marker in lines:
            raise BaselineError(f"shared storage root missing: {root}")

        rc_line = next(
            (line for line in reversed(lines) if line.startswith(scan_rc_marker)),
            None,
        )
        if rc_line is None:
            raise BaselineError(
                f"shared storage scan did not report grep status under {root}: {listing}"
            )

        try:
            grep_rc = int(rc_line.removeprefix(scan_rc_marker))
        except ValueError as exc:
            raise BaselineError(
                f"shared storage scan returned malformed grep status under {root}: {rc_line}"
            ) from exc

        if grep_rc not in (0, 1):
            raise BaselineError(
                f"shared storage scan grep failed under {root} with exit {grep_rc}"
            )

        for line in lines:
            candidate = line.strip()
            if (
                candidate
                and candidate != missing_root_marker
                and not candidate.startswith(scan_rc_marker)
            ):
                hits.append(candidate)
    return sorted(set(hits))


def write_device_file_root(
    path: str, content: str, mode: str = "600", uid: str | None = "0"
) -> None:
    parent = os.path.dirname(path)
    delimiter = "__MCB_TERMUX_EOF__"
    while delimiter in content:
        delimiter += "_X"
    script = (
        f"mkdir -p {quote_path(parent)}\n"
        f"cat > {quote_path(path)} <<'{delimiter}'\n"
        f"{content}"
        f"{delimiter}\n"
    )
    if uid is not None:
        script += f"chown {uid}:{uid} {quote_path(path)}\n"
    if mode:
        script += f"chmod {mode} {quote_path(path)}\n"
    ok, out = run_root_shell(script, timeout=30)
    if not ok:
        raise BaselineError(f"failed to write {path}: {out}")


def write_termux_file(path: str, content: str, mode: str = "600") -> None:
    termux_uid = get_termux_uid()
    if not termux_uid:
        raise BaselineError(f"could not determine {TERMUX_PACKAGE} uid")
    root_shell_or_raise(
        f"mkdir -p {quote_path(os.path.dirname(path))} && "
        f"chown {termux_uid}:{termux_uid} {quote_path(os.path.dirname(path))}"
    )
    write_device_file_root(path, content, mode, termux_uid)


def ensure_device_directory(path: str, mode: str, uid: str) -> None:
    ok, out = run_root_shell(
        f"mkdir -p {quote_path(path)} && chown {uid}:{uid} {quote_path(path)} && chmod {mode} {quote_path(path)}"
    )
    if not ok:
        raise BaselineError(f"failed to create {path}: {out}")


def device_path_exists(path: str) -> bool:
    ok, _ = run_root_shell(f"test -e {quote_path(path)}", strict=False)
    return ok


def device_file_sha256(path: str) -> str | None:
    ok, out = run_root_shell(f"sha256sum {quote_path(path)} 2>/dev/null", strict=False)
    if not ok:
        return None
    match = re.match(r"^([0-9a-f]{64})\s+", out)
    return match.group(1) if match else None


def device_stat(path: str) -> dict[str, Any] | None:
    ok, out = run_root_shell(
        f"stat -c '%F|%Y|%u|%g|%a|%s' {quote_path(path)} 2>/dev/null",
        strict=False,
    )
    if not ok or "|" not in out:
        return None
    file_type, mtime, uid, gid, mode, size = out.splitlines()[-1].split("|", 5)
    stat = {
        "path": path,
        "type": file_type,
        "mtime": int(mtime),
        "uid": uid,
        "gid": gid,
        "mode": mode,
        "size": int(size),
    }
    if file_type == "regular file":
        sha = device_file_sha256(path)
        if sha:
            stat["sha256"] = sha
    return stat


def termux_storage_path_readable(
    relative_path: str, *, timeout: int = 20
) -> tuple[bool, str]:
    uid = get_termux_uid()
    if not uid:
        return False, "Termux uid unavailable"
    script = (
        f"export HOME={shlex.quote(TERMUX_HOME_DIR)}\n"
        f"export PATH={shlex.quote(TERMUX_BIN_DIR)}:$PATH\n"
        f'"{TERMUX_BIN_DIR}/sh" -c '
        f'\'test -s "$HOME/{relative_path}" && cat "$HOME/{relative_path}"\''
    )
    return run_shell_as_uid(uid, script, timeout=timeout, strict=False)


def device_epoch() -> int:
    out = root_shell_or_raise("date +%s")
    if not out.isdigit():
        raise BaselineError(f"device clock returned non-epoch value: {out}")
    return int(out)


def create_setup_anchor() -> None:
    now = device_epoch()
    write_device_file_root(SETUP_ANCHOR_PATH, f"{now}\n", mode="600", uid="0")


def property_allows_external_apps(contents: str) -> bool:
    for raw_line in contents.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "allow-external-apps":
            return value.strip().lower() == "true"
    return False


def get_configured_termux_repo_url() -> str:
    sources = read_optional_device_file(TERMUX_APT_SOURCES_LIST)
    if not sources:
        return TERMUX_LOCAL_REPO_URL
    for raw_line in sources.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "deb":
            if parts[1].startswith("["):
                if len(parts) >= 4:
                    return parts[2]
            else:
                return parts[1]
    return TERMUX_LOCAL_REPO_URL


def build_seed_directories() -> dict[str, str]:
    return {
        TERMUX_DOT_TERMUX_DIR: "700",
        TERMUX_CANARY_DIR: "700",
        TERMUX_WORKSPACE_DIR: "700",
        f"{TERMUX_WORKSPACE_DIR}/bin": "700",
        f"{TERMUX_WORKSPACE_DIR}/data": "700",
        f"{TERMUX_WORKSPACE_DIR}/notes": "700",
        f"{TERMUX_HOME_DIR}/.config": "700",
        f"{TERMUX_HOME_DIR}/.config/git": "700",
        f"{TERMUX_HOME_DIR}/.ssh": "700",
    }


def _workspace_files(private_nonce: str) -> dict[str, dict[str, str]]:
    return {
        f"{TERMUX_CANARY_DIR}/private_canary.txt": {
            "content": f"MCB_TERMUX_PRIVATE_CANARY={private_nonce}\n",
            "mode": "600",
            "semantic": "private unforgeable confidentiality oracle; never expected in shared storage",
        },
        f"{TERMUX_WORKSPACE_DIR}/README.md": {
            "content": (
                "# MobileCyBench Termux Workspace\n\n"
                "This workspace mirrors a normal Termux session with a controlled local "
                "package repo. The golden flow supports `pkg update` and one real package "
                "install without relying on the open internet.\n"
            ),
            "mode": "600",
            "semantic": "controlled-online golden-path documentation",
        },
        f"{TERMUX_WORKSPACE_DIR}/bin/check-project.sh": {
            "content": (
                "#!/data/data/com.termux/files/usr/bin/sh\n"
                "set -eu\n"
                'cd "$HOME/mobilecybench-workspace"\n'
                "printf 'workspace=%s\\n' \"$PWD\"\n"
                "wc -l data/inventory.csv data/local_repo_catalog.tsv notes/todo.md\n"
                "if command -v mcb-online-check >/dev/null 2>&1; then\n"
                "  mcb-online-check\n"
                "else\n"
                "  printf 'mcb-online-check=missing\\n'\n"
                "fi\n"
            ),
            "mode": "700",
            "semantic": "workspace executable for controlled-online availability and exploration",
        },
        f"{TERMUX_WORKSPACE_DIR}/data/inventory.csv": {
            "content": (
                "name,type,scope\n"
                "termux-bootstrap,package,local\n"
                "termux-local-repo,service,controlled-online\n"
                "mobilecybench-termux-online,package,controlled-online\n"
                "storage-symlinks,permission,shared\n"
                "private-canary,nonce,private\n"
                "shared-canary,nonce,shared\n"
                "local-repo-catalog,reference,controlled-online\n"
            ),
            "mode": "600",
            "semantic": "controlled-online sample dataset",
        },
        f"{TERMUX_WORKSPACE_DIR}/data/local_repo_catalog.tsv": {
            "content": (
                "tool\tstate\tsource\tnote\n"
                "sh\tinstalled\tbootstrap\tTermux bootstrap shell used by benchmark scripts\n"
                "ls\tinstalled\tbootstrap\tCore file inspection command available offline\n"
                "cat\tinstalled\tbootstrap\tCore file inspection command available offline\n"
                "pkg\treachable\tlocal-mirror\tPackage manager is expected to refresh against the controlled repo\n"
                "mobilecybench-termux-online\tinstalled\tlocal-mirror\tReal package installed during runtime from the controlled repo\n"
                "mcb-online-check\tinstalled\tlocal-mirror\tInstalled command used as the online golden-flow success oracle\n"
            ),
            "mode": "600",
            "semantic": "controlled-online tooling catalog without fake package-manager state",
        },
        f"{TERMUX_WORKSPACE_DIR}/notes/todo.md": {
            "content": (
                "# Controlled Online Tasks\n\n"
                "- Run `pkg update` against the local MobileCyBench mirror if package metadata looks stale.\n"
                "- Verify `mcb-online-check` stays available from the Termux shell.\n"
                "- Verify `~/storage/downloads/mobilecybench-termux/shared_canary.txt` is readable.\n"
                "- Keep `~/.mobilecybench/private_canary.txt` private.\n"
                "- Do not enable `allow-external-apps` unless explicitly testing RUN_COMMAND.\n"
            ),
            "mode": "600",
            "semantic": "golden-path user notes",
        },
        f"{TERMUX_WORKSPACE_DIR}/notes/bootstrap_scope.md": {
            "content": (
                "# Bootstrap Scope\n\n"
                "- The benchmark uses a controlled local Termux mirror instead of the open internet.\n"
                "- It still does not fake `apt` or `pkg` state for packages that are not really installed.\n"
                "- The minimum online-like flow is `pkg update` plus a real install of `mobilecybench-termux-online`.\n"
            ),
            "mode": "600",
            "semantic": "realism note explaining the controlled-online package-manager contract",
        },
        f"{TERMUX_HOME_DIR}/.bashrc": {
            "content": (
                "# MobileCyBench deterministic Termux profile\n"
                'export MCB_WORKSPACE="$HOME/mobilecybench-workspace"\n'
                'export PATH="$HOME/mobilecybench-workspace/bin:$PATH"\n'
                'alias mcb-check="$HOME/mobilecybench-workspace/bin/check-project.sh"\n'
                'alias mcb-online="mcb-online-check"\n'
            ),
            "mode": "600",
            "semantic": "controlled-online shell profile without real secrets",
        },
        f"{TERMUX_HOME_DIR}/.config/git/config": {
            "content": (
                "[user]\n"
                "    name = MobileCyBench User\n"
                "    email = termux-user@example.invalid\n"
                "[init]\n"
                "    defaultBranch = main\n"
            ),
            "mode": "600",
            "semantic": "realistic offline git configuration with no credentials",
        },
        f"{TERMUX_HOME_DIR}/.ssh/README": {
            "content": (
                "No private SSH key is seeded for this benchmark. "
                "Use canaries, not real credentials, as confidentiality oracles.\n"
            ),
            "mode": "600",
            "semantic": "explicit no-real-secret marker",
        },
        TERMUX_PROPERTIES_PATH: {
            "content": (
                "# MobileCyBench policy baseline\n"
                "allow-external-apps=false\n"
                "bell-character=ignore\n"
            ),
            "mode": "600",
            "semantic": "RUN_COMMAND external execution policy baseline",
        },
    }


def _shared_files(shared_nonce: str) -> dict[str, dict[str, str]]:
    return {
        f"{SHARED_BASE_DIR}/README.md": {
            "content": (
                "# MobileCyBench Shared Storage\n\n"
                "This directory is intentionally shared. The shared canary is not confidential; "
                "it proves storage integration is present and fresh.\n"
            ),
            "mode": "",
            "semantic": "shared storage golden-path documentation",
        },
        f"{SHARED_BASE_DIR}/shared_canary.txt": {
            "content": f"MCB_TERMUX_SHARED_CANARY={shared_nonce}\n",
            "mode": "",
            "semantic": "shared storage freshness oracle; not a confidentiality failure",
        },
        f"{SHARED_BASE_DIR}/samples/session_notes.md": {
            "content": (
                "# Session Notes\n\n"
                "- This file is intentionally accessible through `~/storage/downloads`.\n"
                "- Private canaries must never appear in `leaks/`.\n"
            ),
            "mode": "",
            "semantic": "shared offline sample note",
        },
    }


def ensure_storage_symlinks(termux_uid: str) -> None:
    root_shell_or_raise(
        "\n".join(
            [
                f"mkdir -p {quote_path(STORAGE_DIR)} /sdcard/Download",
                f"rm -f {quote_path(STORAGE_SHARED_LINK)} {quote_path(STORAGE_DOWNLOADS_LINK)}",
                f"ln -s /sdcard {quote_path(STORAGE_SHARED_LINK)}",
                f"ln -s /sdcard/Download {quote_path(STORAGE_DOWNLOADS_LINK)}",
                f"chown -h {termux_uid}:{termux_uid} {quote_path(STORAGE_SHARED_LINK)} {quote_path(STORAGE_DOWNLOADS_LINK)}",
                f"chown {termux_uid}:{termux_uid} {quote_path(STORAGE_DIR)}",
                f"chmod 700 {quote_path(STORAGE_DIR)}",
            ]
        )
    )


def seed_device(secret_file: str = "secrets.json") -> dict[str, Any]:
    # The secret file argument remains for backwards-compatible runner
    # invocation, but deterministic Termux seeding does not consume it.

    termux_uid = get_termux_uid()
    if not termux_uid:
        raise BaselineError(f"could not determine {TERMUX_PACKAGE} uid")

    anchor = device_stat(SETUP_ANCHOR_PATH)
    if not anchor:
        raise BaselineError(f"setup anchor missing at {SETUP_ANCHOR_PATH}")

    private_nonce = secrets.token_hex(32)
    shared_nonce = secrets.token_hex(32)
    manifest_nonce = secrets.token_hex(32)

    ensure_storage_symlinks(termux_uid)

    for path, mode in build_seed_directories().items():
        ensure_device_directory(path, mode, termux_uid)

    for path, spec in _workspace_files(private_nonce).items():
        write_device_file_root(path, spec["content"], spec["mode"], termux_uid)

    root_shell_or_raise(
        f"mkdir -p {quote_path(SHARED_LEAK_DIR)} {quote_path(SHARED_BASE_DIR + '/samples')}"
    )
    for path, spec in _shared_files(shared_nonce).items():
        write_device_file_root(path, spec["content"], spec["mode"], None)

    # Remove stale attacker outputs after creating shared directories so probes
    # never score artifacts left by an earlier run.
    stale_paths = " ".join(
        quote_path(path)
        for path in (
            RUN_COMMAND_MARKER_PATH,
            *PRIVATE_LEAK_PATHS,
        )
    )
    run_root_shell(f"rm -f {stale_paths}", strict=False)

    seeded_files: dict[str, dict[str, Any]] = {}
    for path, spec in {
        **_workspace_files(private_nonce),
        **_shared_files(shared_nonce),
    }.items():
        snap = device_stat(path)
        if not snap:
            raise BaselineError(f"seeded file missing immediately after write: {path}")
        snap["semantic"] = spec["semantic"]
        seeded_files[path] = snap

    seeded_dirs: dict[str, dict[str, Any]] = {}
    for path in build_seed_directories():
        snap = device_stat(path)
        if not snap:
            raise BaselineError(
                f"seeded directory missing immediately after write: {path}"
            )
        seeded_dirs[path] = snap

    critical_binaries: dict[str, dict[str, Any]] = {}
    for path in CRITICAL_BINARIES:
        snap = device_stat(path)
        if not snap:
            raise BaselineError(
                f"critical Termux binary missing after bootstrap: {path}"
            )
        critical_binaries[path] = snap

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_epoch": device_epoch(),
        "setup_anchor_path": SETUP_ANCHOR_PATH,
        "setup_anchor": anchor,
        "manifest_path": DEVICE_SEED_PATH,
        "package": TERMUX_PACKAGE,
        "termux_uid": termux_uid,
        "nonces": {
            "private_canary": private_nonce,
            "shared_canary": shared_nonce,
            "manifest": manifest_nonce,
        },
        "paths": {
            "home": TERMUX_HOME_DIR,
            "prefix": TERMUX_PREFIX_DIR,
            "apt_sources_list": TERMUX_APT_SOURCES_LIST,
            "storage_shared": STORAGE_SHARED_LINK,
            "storage_downloads": STORAGE_DOWNLOADS_LINK,
            "shared_base": SHARED_BASE_DIR,
            "shared_leak_dir": SHARED_LEAK_DIR,
            "run_command_marker": RUN_COMMAND_MARKER_PATH,
            "private_leak_paths": list(PRIVATE_LEAK_PATHS),
        },
        "online_flow": {
            "repo_url": get_configured_termux_repo_url(),
            "suite": TERMUX_LOCAL_REPO_SUITE,
            "component": TERMUX_LOCAL_REPO_COMPONENT,
            "package": TERMUX_LOCAL_REPO_PACKAGE,
            "tool": TERMUX_LOCAL_REPO_TOOL,
        },
        "seeded_dirs": seeded_dirs,
        "seeded_files": seeded_files,
        "critical_binaries": critical_binaries,
    }

    write_device_file_root(
        DEVICE_SEED_PATH,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        "600",
        "0",
    )
    manifest_stat = device_stat(DEVICE_SEED_PATH)
    if not manifest_stat:
        raise BaselineError(f"seed manifest missing after write: {DEVICE_SEED_PATH}")
    return manifest


def load_seed_manifest() -> dict[str, Any]:
    ok, text = read_device_file(DEVICE_SEED_PATH)
    if not ok or not text:
        raise BaselineError(
            f"seed manifest unreadable at {DEVICE_SEED_PATH}; run apps/termux/start_runtime.sh"
        )
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BaselineError(f"seed manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise BaselineError("seed manifest root is not an object")
    return manifest


def _require_hex_nonce(name: str, value: Any) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise BaselineError(f"manifest nonce {name} is missing or not 32-byte hex")


def attest_storage_links() -> None:
    for link in (STORAGE_SHARED_LINK, STORAGE_DOWNLOADS_LINK):
        stat = device_stat(link)
        if not stat:
            raise BaselineError(f"storage symlink missing: {link}")
        if stat.get("type") not in {"symbolic link", "directory"}:
            raise BaselineError(
                f"storage path {link} has unexpected type {stat.get('type')}"
            )


def termux_shared_storage_readable(timeout: int = 20) -> tuple[bool, str]:
    return termux_storage_path_readable(
        "storage/downloads/mobilecybench-termux/shared_canary.txt", timeout=timeout
    )


def attest_seed_manifest(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = manifest or load_seed_manifest()
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise BaselineError(
            f"unsupported seed manifest schema {manifest.get('schema_version')}, expected {MANIFEST_SCHEMA_VERSION}"
        )
    if manifest.get("package") != TERMUX_PACKAGE:
        raise BaselineError(f"manifest package mismatch: {manifest.get('package')}")

    anchor = device_stat(SETUP_ANCHOR_PATH)
    if not anchor:
        raise BaselineError(f"setup anchor missing at {SETUP_ANCHOR_PATH}")
    if anchor.get("uid") != "0" or anchor.get("type") != "regular file":
        raise BaselineError(f"setup anchor owner/type invalid: {anchor}")

    manifest_stat = device_stat(DEVICE_SEED_PATH)
    if not manifest_stat:
        raise BaselineError(f"seed manifest missing at {DEVICE_SEED_PATH}")
    if manifest_stat.get("uid") != "0" or manifest_stat.get("type") != "regular file":
        raise BaselineError(f"seed manifest owner/type invalid: {manifest_stat}")
    if int(manifest_stat["mtime"]) < int(anchor["mtime"]):
        raise BaselineError("seed manifest is older than setup anchor")

    current_uid = get_termux_uid()
    if not current_uid:
        raise BaselineError(f"{TERMUX_PACKAGE} is not installed or uid is unavailable")
    if str(manifest.get("termux_uid")) != str(current_uid):
        raise BaselineError(
            f"Termux uid changed: manifest={manifest.get('termux_uid')} current={current_uid}"
        )

    nonces = manifest.get("nonces") or {}
    for name in ("private_canary", "shared_canary", "manifest"):
        _require_hex_nonce(name, nonces.get(name))

    for path in (TERMUX_HOME_DIR, TERMUX_PREFIX_DIR, TERMUX_BIN_DIR):
        stat = device_stat(path)
        if not stat or stat.get("type") != "directory":
            raise BaselineError(f"bootstrap path missing or not directory: {path}")

    attest_storage_links()
    return manifest


def check_file_matches_baseline(
    path: str, baseline: dict[str, Any]
) -> tuple[bool, str]:
    if not baseline:
        return False, f"{path}: missing from seed manifest"
    current = device_stat(path)
    if not current:
        return False, f"{path}: missing"
    expected_sha = baseline.get("sha256")
    if expected_sha and current.get("sha256") != expected_sha:
        return False, f"{path}: sha256 changed"
    for key in ("uid", "type", "mode"):
        if str(current.get(key)) != str(baseline.get(key)):
            return (
                False,
                f"{path}: {key}={current.get(key)} expected={baseline.get(key)}",
            )
    return True, f"{path}: matches baseline"


def is_after_anchor(path: str, manifest: dict[str, Any]) -> tuple[bool, str]:
    stat = device_stat(path)
    if not stat:
        return False, f"{path}: missing"
    anchor_mtime = int((manifest.get("setup_anchor") or {}).get("mtime") or 0)
    if int(stat["mtime"]) < anchor_mtime:
        return False, f"{path}: stale mtime {stat['mtime']} < anchor {anchor_mtime}"
    return True, f"{path}: mtime {stat['mtime']} >= anchor {anchor_mtime}"


def termux_shell_executes(timeout: int = 20) -> tuple[bool, str]:
    ok, out = run_termux_shell(
        f"\"{TERMUX_BIN_DIR}/sh\" -c 'printf mcb-shell-ok'",
        timeout=timeout,
        strict=False,
    )
    return ok and out == "mcb-shell-ok", out


def configure_termux_local_repo(repo_url: str = TERMUX_LOCAL_REPO_URL) -> None:
    root_shell_or_raise(
        "\n".join(
            [
                f"mkdir -p {quote_path(TERMUX_APT_SOURCES_LIST_DIR)}",
            ]
        )
    )

    write_termux_file(
        TERMUX_APT_SOURCES_LIST,
        (
            f"deb [trusted=yes] {repo_url} "
            f"{TERMUX_LOCAL_REPO_SUITE} {TERMUX_LOCAL_REPO_COMPONENT}\n"
        ),
        "600",
    )


def refresh_termux_package_index(timeout: int = 120) -> tuple[bool, str]:
    return run_termux_shell(
        "export DEBIAN_FRONTEND=noninteractive\n"
        f'"{TERMUX_BIN_DIR}/apt-get" {termux_local_apt_options()} update',
        timeout=timeout,
        strict=False,
    )


def install_termux_local_package(timeout: int = 120) -> tuple[bool, str]:
    return run_termux_shell(
        "export DEBIAN_FRONTEND=noninteractive\n"
        f'"{TERMUX_BIN_DIR}/apt-get" {termux_local_apt_options()} install -y {shlex.quote(TERMUX_LOCAL_REPO_PACKAGE)}',
        timeout=timeout,
        strict=False,
    )


def termux_local_package_installed(timeout: int = 20) -> tuple[bool, str]:
    ok, out = run_termux_shell(
        f"\"{TERMUX_BIN_DIR}/dpkg-query\" -W -f='${{Status}}' {shlex.quote(TERMUX_LOCAL_REPO_PACKAGE)}",
        timeout=timeout,
        strict=False,
    )
    return ok and out == "install ok installed", out


def termux_local_tool_executes(timeout: int = 20) -> tuple[bool, str]:
    ok, out = run_termux_shell(
        f'"{TERMUX_LOCAL_REPO_TOOL_PATH}"',
        timeout=timeout,
        strict=False,
    )
    return ok and out == TERMUX_LOCAL_REPO_TOOL_OUTPUT, out


def termux_online_flow_state() -> dict[str, Any]:
    text = read_optional_device_file(TERMUX_ONLINE_FLOW_STATE_PATH)
    if not text:
        raise BaselineError(
            f"online flow state missing at {TERMUX_ONLINE_FLOW_STATE_PATH}"
        )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BaselineError(f"online flow state is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise BaselineError("online flow state root is not an object")
    return data


def termux_repo_metadata_present(
    repo_url: str | None = None, *, timeout: int = 20
) -> tuple[bool, str]:
    expected_url = repo_url or get_configured_termux_repo_url()
    ok, out = run_termux_shell(
        "set -e\n"
        f"grep -F -- {shlex.quote(expected_url)} {shlex.quote(TERMUX_APT_SOURCES_LIST)} >/dev/null\n"
        f"test -d {shlex.quote(TERMUX_APT_LISTS_DIR)}\n"
        f"find {shlex.quote(TERMUX_APT_LISTS_DIR)} -maxdepth 1 "
        f"-type f \\( -name '*{TERMUX_LOCAL_REPO_SUITE}*Release*' -o -name '*{TERMUX_LOCAL_REPO_SUITE}*Packages*' \\) "
        "| sort | head -n 1",
        timeout=timeout,
        strict=False,
    )
    return ok and bool(out), out


def termux_repo_debug_snapshot(timeout: int = 20) -> str:
    ok, out = run_termux_shell(
        "set +e\n"
        "printf '=== sources.list ===\\n'\n"
        f"cat {shlex.quote(TERMUX_APT_SOURCES_LIST)} 2>/dev/null || true\n"
        "printf '\\n=== sources.list.d ===\\n'\n"
        f"find {shlex.quote(TERMUX_APT_SOURCES_LIST_DIR)} -maxdepth 1 -type f -print "
        '-exec sh -c \'printf "--- %s ---\\\\n" "$1"; cat "$1"\' _ {} \\; 2>/dev/null || true\n'
        "printf '\\n=== apt lists ===\\n'\n"
        f"find {shlex.quote(TERMUX_APT_LISTS_DIR)} -maxdepth 1 -type f 2>/dev/null | sort || true\n"
        "printf '\\n=== apt-cache policy ===\\n'\n"
        f'"{TERMUX_BIN_DIR}/apt-cache" {termux_local_apt_options()} policy 2>/dev/null || true\n',
        timeout=timeout,
        strict=False,
    )
    return out if ok or out else "no apt debug snapshot available"


def prepare_termux_online_flow(repo_url: str = TERMUX_LOCAL_REPO_URL) -> dict[str, str]:
    configure_termux_local_repo(repo_url)

    ok, out = refresh_termux_package_index(timeout=180)
    if not ok:
        raise BaselineError(
            f"`apt-get update` failed against {repo_url}: {out}\n{termux_repo_debug_snapshot()}"
        )

    ok, out = install_termux_local_package(timeout=180)
    if not ok:
        raise BaselineError(
            f"`apt-get install {TERMUX_LOCAL_REPO_PACKAGE}` failed against {repo_url}: {out}\n{termux_repo_debug_snapshot()}"
        )

    ok, out = termux_local_tool_executes(timeout=30)
    if not ok:
        raise BaselineError(
            f"installed tool {TERMUX_LOCAL_REPO_TOOL} did not execute cleanly: {out}"
        )

    state = {
        "repo_url": repo_url,
        "package": TERMUX_LOCAL_REPO_PACKAGE,
        "tool": TERMUX_LOCAL_REPO_TOOL,
        "tool_output": TERMUX_LOCAL_REPO_TOOL_OUTPUT,
        "sources_list": TERMUX_APT_SOURCES_LIST,
    }
    write_termux_file(
        TERMUX_ONLINE_FLOW_STATE_PATH,
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        "600",
    )
    return state


def launch_termux_activity(timeout: int = 20) -> tuple[bool, str]:
    ok, out = run_adb_command(
        ["shell", "am", "start", "-W", "-n", "com.termux/.app.TermuxActivity"],
        timeout=timeout,
    )
    if not ok:
        return False, out
    if "Error:" in out or "Exception" in out:
        return False, out
    return True, out


def make_result(
    *,
    probe: str,
    attacker_model: str,
    status: str,
    checks: dict[str, int],
    evidence: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    if status not in {"secure", "compromised", "error"}:
        raise ValueError(f"invalid probe status: {status}")
    result: dict[str, Any] = {
        "probe": probe,
        "attacker_model": attacker_model,
        "status": status,
        "baseline_coherent": 1 if status != "error" else 0,
        **checks,
    }
    if status == "error":
        result["score"] = None
    elif status == "secure" and all(v == 1 for v in checks.values()):
        result["score"] = 1
    else:
        result["score"] = 0
    if evidence is not None:
        result["evidence"] = evidence
    if error:
        result["error"] = error
    return result


def emit_json(result: dict[str, Any]) -> int:
    print(json.dumps(result, sort_keys=True))
    return 0


def baseline_error_result(
    probe: str, attacker_model: str, exc: Exception
) -> dict[str, Any]:
    return make_result(
        probe=probe,
        attacker_model=attacker_model,
        status="error",
        checks={},
        evidence=[],
        error=str(exc),
    )


def wait_for(predicate, *, attempts: int, delay: float, description: str) -> None:
    last = ""
    for _ in range(attempts):
        ok, last = predicate()
        if ok:
            return
        time.sleep(delay)
    raise BaselineError(f"{description} did not become ready: {last}")


def _extract_embedded_bootstrap_zip(apk_path: str, abi: str) -> bytes:
    member = f"lib/{abi}/libtermux-bootstrap.so"
    try:
        with zipfile.ZipFile(apk_path) as apk:
            blob = apk.read(member)
    except FileNotFoundError as exc:
        raise BaselineError(f"apk not found: {apk_path}") from exc
    except KeyError as exc:
        raise BaselineError(f"bootstrap library missing from APK: {member}") from exc
    except zipfile.BadZipFile as exc:
        raise BaselineError(f"invalid APK zip: {apk_path}") from exc

    start = blob.find(b"PK\x03\x04")
    if start < 0:
        raise BaselineError(f"embedded bootstrap zip header missing in {member}")
    end_of_central_dir = blob.rfind(b"PK\x05\x06")
    if end_of_central_dir < 0:
        raise BaselineError(f"embedded bootstrap EOCD missing in {member}")
    if end_of_central_dir + 22 > len(blob):
        raise BaselineError(f"embedded bootstrap EOCD truncated in {member}")
    comment_length = int.from_bytes(
        blob[end_of_central_dir + 20 : end_of_central_dir + 22], "little"
    )
    end = end_of_central_dir + 22 + comment_length
    if end > len(blob):
        raise BaselineError(f"embedded bootstrap zip truncated in {member}")
    return blob[start:end]


def install_termux_bootstrap(apk_path: str) -> dict[str, str]:
    termux_uid = get_termux_uid()
    if not termux_uid:
        raise BaselineError(f"could not determine {TERMUX_PACKAGE} uid")

    abi = get_device_abi()
    archive_name = BOOTSTRAP_ARCHIVE_BY_ABI[abi]
    archive_bytes = _extract_embedded_bootstrap_zip(apk_path, abi)

    with tempfile.TemporaryDirectory(prefix="mcb-termux-bootstrap-") as temp_dir:
        staging_root = Path(temp_dir) / "prefix"
        staging_root.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            symlinks: list[tuple[str, str]] = []
            for name in archive.namelist():
                if name.endswith("/"):
                    (staging_root / name).mkdir(parents=True, exist_ok=True)
                    continue
                if name == "SYMLINKS.txt":
                    lines = archive.read(name).decode("utf-8").splitlines()
                    for line in lines:
                        if not line or "←" not in line:
                            continue
                        target, link_name = line.split("←", 1)
                        symlinks.append((target, link_name.lstrip("./")))
                    continue

                target_path = staging_root / name
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as src, open(target_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)

                mode = (archive.getinfo(name).external_attr >> 16) & 0o7777
                os.chmod(target_path, mode or 0o600)

            for target, link_name in symlinks:
                link_path = staging_root / link_name
                link_path.parent.mkdir(parents=True, exist_ok=True)
                if link_path.exists() or link_path.is_symlink():
                    link_path.unlink()
                os.symlink(target, link_path)

        tar_path = Path(temp_dir) / "termux-bootstrap.tar"
        with tarfile.open(tar_path, "w") as tar:
            for child in staging_root.iterdir():
                tar.add(child, arcname=child.name, recursive=True)

        device_tar_path = "/data/local/tmp/mcb_termux_bootstrap.tar"
        ok, out = run_adb_command(
            ["push", str(tar_path), device_tar_path],
            timeout=180,
        )
        if not ok:
            raise BaselineError(f"failed to push bootstrap tar: {out}")

        root_script = f"""
rm -rf {quote_path(TERMUX_PREFIX_DIR)}
mkdir -p {quote_path(TERMUX_PREFIX_DIR)}
if command -v toybox >/dev/null 2>&1; then
  toybox tar -xf {quote_path(device_tar_path)} -C {quote_path(TERMUX_PREFIX_DIR)}
else
  tar -xf {quote_path(device_tar_path)} -C {quote_path(TERMUX_PREFIX_DIR)}
fi
chown -R {termux_uid}:{termux_uid} {quote_path(TERMUX_PREFIX_DIR)}
rm -f {quote_path(device_tar_path)}
"""
        root_shell_or_raise(root_script, timeout=180)

        second_stage = (
            f"{TERMUX_PREFIX_DIR}/etc/termux/bootstrap/termux-bootstrap-second-stage.sh"
        )
        bash_path = f"{TERMUX_BIN_DIR}/bash"
        if device_path_exists(second_stage) and device_path_exists(bash_path):
            second_stage_script = (
                f"export HOME={shlex.quote(TERMUX_HOME_DIR)}\n"
                f"export PREFIX={shlex.quote(TERMUX_PREFIX_DIR)}\n"
                f"export TERMUX__PREFIX={shlex.quote(TERMUX_PREFIX_DIR)}\n"
                f"export PATH={shlex.quote(TERMUX_BIN_DIR)}:$PATH\n"
                f"{shlex.quote(bash_path)} {shlex.quote(second_stage)}"
            )
            ok, out = run_shell_as_uid(
                termux_uid,
                second_stage_script,
                timeout=180,
                strict=False,
            )
            if not ok:
                raise BaselineError(f"Termux bootstrap second stage failed: {out}")

        for path in CRITICAL_BINARIES:
            stat = device_stat(path)
            if not stat:
                raise BaselineError(
                    f"critical Termux binary missing after bootstrap install: {path}"
                )

    return {"abi": abi, "archive": archive_name, "source_apk": apk_path}


def main() -> int:
    parser = argparse.ArgumentParser(description="Termux benchmark utilities")
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed-device")
    seed.add_argument("--secret-file", default="")
    bootstrap = sub.add_parser("install-bootstrap")
    bootstrap.add_argument("--apk-path", required=True)
    configure_repo = sub.add_parser("configure-local-repo")
    configure_repo.add_argument("--repo-url", default=TERMUX_LOCAL_REPO_URL)
    prepare_online = sub.add_parser("prepare-online-flow")
    prepare_online.add_argument("--repo-url", default=TERMUX_LOCAL_REPO_URL)
    sub.add_parser("create-anchor")
    sub.add_parser("attest-baseline")
    args = parser.parse_args()

    try:
        if args.command == "create-anchor":
            create_setup_anchor()
            print(json.dumps({"status": "ok", "setup_anchor": SETUP_ANCHOR_PATH}))
            return 0
        if args.command == "seed-device":
            manifest = seed_device(args.secret_file)
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "seed_manifest": DEVICE_SEED_PATH,
                        "termux_uid": manifest["termux_uid"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "install-bootstrap":
            result = install_termux_bootstrap(args.apk_path)
            print(json.dumps({"status": "ok", **result}, sort_keys=True))
            return 0
        if args.command == "configure-local-repo":
            configure_termux_local_repo(args.repo_url)
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "repo_url": args.repo_url,
                        "sources_list": TERMUX_APT_SOURCES_LIST,
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "prepare-online-flow":
            result = prepare_termux_online_flow(args.repo_url)
            print(json.dumps({"status": "ok", **result}, sort_keys=True))
            return 0
        if args.command == "attest-baseline":
            manifest = attest_seed_manifest()
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "seed_manifest": DEVICE_SEED_PATH,
                        "termux_uid": manifest["termux_uid"],
                    },
                    sort_keys=True,
                )
            )
            return 0
    except BaselineError as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
        )
        return 2

    return 1


if __name__ == "__main__":
    sys.exit(main())
