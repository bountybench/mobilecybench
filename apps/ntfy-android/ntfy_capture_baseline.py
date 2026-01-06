#!/usr/bin/env python3
"""
Capture an expanded baseline snapshot of an Android app's private storage.

Outputs JSONL with: path, sha256, size, mtime, content_b64 (small text), content_truncated.
"""

import argparse
import base64
import json
import os
import shlex
import subprocess
from pathlib import Path

TEXT_EXTS = {".xml", ".json", ".txt", ".log", ".conf", ".properties"}


def adb_shell(cmd):
    safe_cmd = shlex.quote(cmd)
    return subprocess.check_output(
        ["adb", "shell", f"su 0 sh -c {safe_cmd}"], text=True
    )


def adb_shell_allow_fail(cmd):
    safe_cmd = shlex.quote(cmd)
    result = subprocess.run(
        ["adb", "shell", f"su 0 sh -c {safe_cmd}"],
        text=True,
        capture_output=True,
    )
    return result.stdout


def resolve_data_dir(candidate):
    if not candidate:
        return None
    if not candidate.startswith("/data/"):
        return None
    pwd_out = adb_shell_allow_fail(f'cd "{candidate}" 2>/dev/null && pwd').strip()
    if not pwd_out:
        return None
    if pwd_out == "/" and candidate != "/":
        return None
    return pwd_out


def parse_args():
    parser = argparse.ArgumentParser(description="Capture expanded Android baseline")
    parser.add_argument("--package", required=True)
    parser.add_argument("--target-dir", required=True)
    parser.add_argument("--baseline-file", required=True)
    parser.add_argument("--max-bytes", type=int, default=8192)
    return parser.parse_args()


def main():
    args = parse_args()
    pkg = args.package
    target_dir = args.target_dir
    fallback_dir = f"/data/user/0/{pkg}"
    baseline_file = Path(args.baseline_file)

    data_dir = None
    try:
        dumpsys = subprocess.check_output(
            ["adb", "shell", "dumpsys", "package", pkg],
            text=True,
        )
        for line in dumpsys.splitlines():
            line = line.strip()
            if line.startswith("dataDir="):
                data_dir = line.split("=", 1)[1].strip()
                break
    except subprocess.CalledProcessError:
        data_dir = None

    data_dir = resolve_data_dir(data_dir)
    if not data_dir:
        data_dir = resolve_data_dir(target_dir) or resolve_data_dir(fallback_dir)
    if not data_dir:
        raise SystemExit(
            f"App data directory not found: tried {target_dir} and {fallback_dir}"
        )

    if not data_dir.startswith("/data/"):
        raise SystemExit(f"Resolved app data directory is invalid: {data_dir!r}")

    find_cmd = (
        f'cd "{data_dir}" 2>/dev/null && '
        'find . -type f ! -path "./cache/*" ! -path "./code_cache/*" -print0 2>/dev/null'
    )
    raw = adb_shell_allow_fail(find_cmd)
    if not raw:
        raise SystemExit(f"No files enumerated from {data_dir}")

    paths = [p for p in raw.split("\x00") if p]
    entries = []

    for rel_path in sorted(paths):
        full_path = os.path.join(data_dir, rel_path.lstrip("./"))
        sha_out = adb_shell_allow_fail(f'sha256sum "{full_path}" 2>/dev/null').strip()
        if not sha_out:
            continue
        sha = sha_out.split()[0]
        stat_out = (
            adb_shell_allow_fail(
                f'stat -c "%s %Y" "{full_path}" 2>/dev/null || echo "0 0"'
            )
            .strip()
            .split()
        )
        size = int(stat_out[0]) if stat_out else 0
        mtime = int(stat_out[1]) if len(stat_out) > 1 else 0

        ext = Path(rel_path).suffix.lower()
        content_b64 = None
        truncated = False
        if ext in TEXT_EXTS:
            data = subprocess.check_output(
                [
                    "adb",
                    "shell",
                    f"su 0 sh -c {shlex.quote(f'head -c {args.max_bytes} \"{full_path}\"')}",
                ],
            )
            truncated = size > args.max_bytes
            content_b64 = base64.b64encode(data).decode("ascii")

        entries.append(
            {
                "path": rel_path,
                "sha256": sha,
                "size": size,
                "mtime": mtime,
                "content_b64": content_b64,
                "content_truncated": truncated,
            }
        )

    baseline_file.parent.mkdir(parents=True, exist_ok=True)
    with baseline_file.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
