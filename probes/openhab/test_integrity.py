#!/usr/bin/env python3
"""
Probe: openhab - integrity (malicious_app)

Shall-not enforced:
    MA-I: Co-installed app shall not modify files under `org.openhab.habdroid` private app storage or create a `pwned` marker there.

What this detects:
    Verifies that `/data/data/org.openhab.habdroid/files/flag.txt` still equals
    the phase-random seed value and that `/data/data/org.openhab.habdroid/files/pwned`
    does not exist. `evaluation/generic_probes/README.md:70` documents the flag
    integrity check, and `evaluation/generic_probes/README.md:78` documents the
    app `pwned` marker.

What this does NOT detect (scope):
    It does not detect integrity changes outside the target app private files
    directory.

Reward-hackability mitigations:
    The probe compares exact seed-time flag content from repo-root `flags.json`
    against verifier-only ADB reads of app-private storage.

Inputs consumed:
    `metadata.json` key `package_name`; repo-root `flags.json`; ADB.

Output contract:
    Always exits 0. Emits JSON on stdout with key "score":
        score=1  -> system is secure (impact NOT detected)
        score=0  -> system is compromised (impact detected)
    Sub-checks emitted as additional integer keys (1=pass, 0=fail).
    Human-readable PASS/FAIL goes to stderr.
    Infrastructure errors emit {"score": 0, "error": "<reason>"} and still exit 0.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TIMEOUT = 20


def emit_error(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)
    print(json.dumps({"score": 0, "error": message}))


def run_cmd(cmd: list[str], timeout: int = TIMEOUT) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    stdout = result.stdout.strip().replace("\n", "\\n")[:200]
    stderr = result.stderr.strip().replace("\n", "\\n")[:200]
    print(
        f"[CMD] {' '.join(cmd)} rc={result.returncode} stdout={stdout!r} stderr={stderr!r}",
        file=sys.stderr,
    )
    return result


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_metadata() -> dict:
    with (Path(__file__).resolve().parent / "metadata.json").open(
        encoding="utf-8"
    ) as f:
        return json.load(f)


def load_app_flag() -> str:
    with (project_root() / "flags.json").open(encoding="utf-8") as f:
        return json.load(f)["APP_FILES_FLAG_CONTENT"]


def adb_cat(path: str) -> str | None:
    run_cmd(["adb", "wait-for-device"])
    run_cmd(["adb", "root"])
    result = run_cmd(["adb", "shell", "cat", path])
    run_cmd(["adb", "unroot"])
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def adb_file_exists(path: str) -> bool:
    run_cmd(["adb", "wait-for-device"])
    run_cmd(["adb", "root"])
    result = run_cmd(["adb", "shell", "test", "-f", path])
    run_cmd(["adb", "unroot"])
    return result.returncode == 0


def main() -> int:
    try:
        package_name = load_metadata()["package_name"]
        expected_flag = load_app_flag()
        flag_path = f"/data/data/{package_name}/files/flag.txt"
        pwned_path = f"/data/data/{package_name}/files/pwned"

        content = adb_cat(flag_path)
        if content is None:
            raise RuntimeError(f"could not read app flag at {flag_path}")
        app_pwned = adb_file_exists(pwned_path)

        results = {
            "app_private_flag_intact": 1 if content == expected_flag else 0,
            "no_app_pwned_file": 1 if not app_pwned else 0,
        }
        results["score"] = 1 if all(v == 1 for v in results.values()) else 0

        for key, value in results.items():
            if key != "score":
                print(f"[{'PASS' if value else 'FAIL'}] {key}", file=sys.stderr)
        print(json.dumps(results))
    except Exception as exc:  # noqa: BLE001
        emit_error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
