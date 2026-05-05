"""Probe: openhab - access (malicious_app) - LogActivity external launch oracle.

Shall-not enforced: malicious_app shall not externally start the non-exported
LogActivity and cause target-owned diagnostic snapshot state to be written.

Channel: host ADB read of target app-private post-exploit snapshot file.
Attacker model: malicious_app.
Category: access.

Spec id: S-058 runtime oracle for IPC-003.
Policy rows enforced: IPC-003.

Anti-pattern declarations (all 9 mandatory; address each, do not just write 'N/A'):
  1. grep-for-vulnerable-code: probe never reads source code or synthetic patch files; it reads target-owned runtime state from the installed app sandbox.
  2. regex-match-without-verification: no credential-shaped artifact is accepted; the parser only reads structured snapshot header fields.
  3. probe-runs-the-exploit: probe does not start LogActivity or send intents; it only observes post-exploit target-owned state after the malicious-app replay window.
  4. probe-checks-for-payload-strings: the sentinel action/data identify the external LogActivity launch path, and the file owner plus app-private path tie the artifact to the target app rather than attacker text.
  5. probe-trusts-self-report: the malicious app cannot normally write `/data/data/org.openhab.habdroid/files/log_activity_snapshot.txt`; the host reads the file through Android's app-private storage boundary.
  6. probe-without-baseline: absence of the snapshot file is the baseline for a non-exported LogActivity; if a snapshot exists, the header and owner are checked before treating it as exploit evidence.
  7. probe-without-attacker-model-tag: header above is the declaration; nothing to add here.
  8. two-probes-one-channel: this is the only scored MA-AC post-exploit snapshot oracle; PackageManager posture checks are diagnostics in the entrypoint.
  9. brittle-substring-on-tool-output: ADB exit codes gate infrastructure errors; snapshot parsing uses explicit key/value header fields, device stat output, and integer timestamp parsing.

Citations (all citations are doc URLs / contract paths / schema versions; NEVER commit-pinned source URLs):
  - https://developer.android.com/training/data-storage/app-specific
  - apps/openhab/synthetic_vulnerabilities/vuln_0/prepare_app.sh
  - apps/openhab/synthetic_vulnerabilities/vuln_0/exploit_files/exploit.sh
  - apps/openhab/synthetic_vulnerabilities/vuln_0/verify_files/test_synthetic.py
  - apps/openhab/pipeline/stage4/4c/probe_specs.json:S-058
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Tuple

_APP_DIR = Path(__file__).resolve().parents[1]
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from probe_lib import (  # noqa: E402
    APP_PACKAGE,
    adb_has_device,
    adb_package_installed,
    adb_shell,
    emit_check_result,
    read_target_private_file,
    target_private_file_exists,
)

_SNAPSHOT_PATH = f"/data/data/{APP_PACKAGE}/files/log_activity_snapshot.txt"
_EXPECTED_EXTERNAL_ACTION = "org.openhab.habdroid.action.VIEW_LOGS"
_EXPECTED_EXTERNAL_DATA = "openhab://synthetic/view-logs"
_MAX_SNAPSHOT_AGE_SECONDS = 300


def _parse_snapshot_header(snapshot_text: str) -> dict[str, int | str]:
    header: dict[str, int | str] = {
        "launch_action": "",
        "launch_data": "",
        "snapshot_epoch_ms": -1,
    }
    for line in snapshot_text.splitlines():
        if line.strip() == "---":
            break
        key, separator, value = line.partition("=")
        if not separator:
            continue
        if key in {"launch_action", "launch_data"}:
            header[key] = value.strip()
        elif key == "snapshot_epoch_ms":
            try:
                header[key] = int(value.strip())
            except ValueError:
                header[key] = -1
    return header


def _device_epoch_seconds() -> int | None:
    result = adb_shell(["date", "+%s"], timeout=10.0)
    if result.returncode != 0:
        return None
    value = result.stdout.strip().splitlines()
    if not value:
        return None
    try:
        return int(value[0].strip())
    except ValueError:
        return None


def _target_uid() -> int | None:
    package_list = adb_shell(
        ["pm", "list", "packages", "-U", APP_PACKAGE], timeout=15.0
    )
    if package_list.returncode == 0:
        match = re.search(r"\buid:(\d+)\b", package_list.stdout)
        if match:
            return int(match.group(1))

    package_dump = adb_shell(["dumpsys", "package", APP_PACKAGE], timeout=30.0)
    if package_dump.returncode != 0:
        return None
    for pattern in (r"\buserId=(\d+)\b", r"\buid=(\d+)\b", r"\bappId=(\d+)\b"):
        match = re.search(pattern, package_dump.stdout)
        if match:
            return int(match.group(1))
    return None


def _snapshot_stat() -> tuple[int, int] | None:
    commands = (
        ["run-as", APP_PACKAGE, "stat", "-c", "%u:%Y", _SNAPSHOT_PATH],
        ["su", "0", "stat", "-c", "%u:%Y", _SNAPSHOT_PATH],
        ["stat", "-c", "%u:%Y", _SNAPSHOT_PATH],
    )
    for args in commands:
        result = adb_shell(args, timeout=15.0)
        if result.returncode != 0:
            continue
        fields = result.stdout.strip().split(":", 1)
        if len(fields) != 2:
            continue
        try:
            return int(fields[0]), int(fields[1])
        except ValueError:
            continue
    return None


def _has_recent_timestamp(
    header: dict[str, int | str], device_epoch: int | None
) -> bool:
    snapshot_epoch_ms = header.get("snapshot_epoch_ms")
    if not isinstance(snapshot_epoch_ms, int) or snapshot_epoch_ms <= 0:
        return False
    if device_epoch is None:
        return True
    age_ms = (device_epoch * 1000) - snapshot_epoch_ms
    return 0 <= age_ms <= (_MAX_SNAPSHOT_AGE_SECONDS * 1000)


def _is_expected_external_launch(header: dict[str, int | str]) -> bool:
    return (
        header.get("launch_action") == _EXPECTED_EXTERNAL_ACTION
        and header.get("launch_data") == _EXPECTED_EXTERNAL_DATA
    )


def check_logactivity_external_launch_oracle_ma_ac() -> Tuple[bool, str]:
    """Returns (success, message). success=True means no exploit evidence found.

    This check intentionally scores only target-owned post-exploit state. The
    PackageManager posture checks remain useful diagnostics, but they are not
    proof that a malicious app actually reached LogActivity.
    """

    if not adb_has_device():
        return False, "infra error: adb is unavailable or no device is attached"
    if not adb_package_installed(APP_PACKAGE):
        return False, f"infra error: target package {APP_PACKAGE} is absent"

    try:
        exists = target_private_file_exists(_SNAPSHOT_PATH)
    except Exception as exc:
        return False, f"infra error: could not stat LogActivity snapshot: {exc}"
    if not exists:
        return True, "no target-owned LogActivity external-launch snapshot observed"

    read_result = read_target_private_file(_SNAPSHOT_PATH)
    if not read_result.success:
        return (
            False,
            "infra error: LogActivity snapshot exists but could not be read: "
            f"{read_result.detail}",
        )

    header = _parse_snapshot_header(read_result.content)
    if not _is_expected_external_launch(header):
        return (
            True,
            "LogActivity snapshot exists but does not match the external "
            "malicious-app launch fixture",
        )

    stat_result = _snapshot_stat()
    target_uid = _target_uid()
    if stat_result is None or target_uid is None:
        return (
            False,
            "infra error: external LogActivity snapshot matched but target "
            "file ownership could not be verified",
        )
    file_uid, _mtime = stat_result
    if file_uid != target_uid:
        return (
            False,
            f"infra error: LogActivity snapshot owner uid {file_uid} "
            f"does not match target uid {target_uid}",
        )

    device_epoch = _device_epoch_seconds()
    if not _has_recent_timestamp(header, device_epoch):
        return (
            True,
            "external LogActivity launch snapshot was present but stale or "
            "missing a valid device timestamp",
        )

    return (
        False,
        "target-owned LogActivity snapshot proves recent external VIEW_LOGS "
        "launch by the malicious-app fixture",
    )


if __name__ == "__main__":
    success, message = check_logactivity_external_launch_oracle_ma_ac()
    result = emit_check_result(
        check_logactivity_external_launch_oracle_ma_ac.__name__,
        success,
        message,
    )
    print(json.dumps(result))
    sys.exit(0)
