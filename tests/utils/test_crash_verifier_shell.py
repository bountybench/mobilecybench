"""Shell-level tests for the shared crash verifier orchestration."""

from __future__ import annotations

import os
import subprocess
import textwrap
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CRASH_UTILS = REPO_ROOT / "utils" / "verify" / "crash"
VERIFIER_COMMON = REPO_ROOT / "utils" / "verify" / "verifier_common.sh"


EXIT_INFO_TWO_CRASHES = """\
  Historical Process Exit for uid=10123
    timestamp=2025-01-15 10:35:00.000 pid=2000
      process=com.test reason=4 (APP CRASH)
    timestamp=2025-01-15 10:30:00.000 pid=1000
      process=com.test reason=4 (APP CRASH)
"""


def _write_fake_adb(tmp_path: Path, exit_info: str) -> Path:
    exit_info_file = tmp_path / "exit-info.txt"
    exit_info_file.write_text(exit_info)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    adb = fake_bin / "adb"
    adb.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail

            if [ "${1:-}" = "shell" ] && [ "${2:-}" = "date" ]; then
                echo "+0000"
                exit 0
            fi

            if [ "${1:-}" = "shell" ] && [ "${2:-}" = "dumpsys" ]; then
                cat "$FAKE_EXIT_INFO"
                exit 0
            fi

            if [ "${1:-}" = "shell" ] && [ "${2:-}" = "pm" ]; then
                echo "package:com.test uid:10123"
                exit 0
            fi

            echo "unexpected adb invocation: $*" >&2
            exit 99
            """
        )
    )
    adb.chmod(0o755)
    return fake_bin


def _start_fake_sniffer(tmp_path: Path) -> tuple[subprocess.Popen, Path]:
    log = tmp_path / "crash_sniffer.log"
    log.write_text("")
    pid_file = tmp_path / "crash_sniffer.pid"
    proc = subprocess.Popen(
        [
            "bash",
            "-c",
            'exec -a "adb logcat -b crash -v threadtime,uid,printable" sleep 60',
        ]
    )
    time.sleep(0.1)
    pid_file.write_text(str(proc.pid))
    return proc, pid_file


def _run_crash_verifier(
    tmp_path: Path, signature_script: Path
) -> subprocess.CompletedProcess:
    fake_bin = _write_fake_adb(tmp_path, EXIT_INFO_TWO_CRASHES)
    sniffer_proc, pid_file = _start_fake_sniffer(tmp_path)
    epoch_file = tmp_path / "device_epoch_baseline.txt"
    epoch_file.write_text("0")
    runner = tmp_path / "run_verifier.sh"
    runner.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            source "{VERIFIER_COMMON}"
            source "{CRASH_UTILS / "crash_verifier.sh"}"
            run_crash_verification \\
                "com.test" \\
                "{tmp_path / "crash_sniffer.log"}" \\
                "{pid_file}" \\
                "{epoch_file}" \\
                "{signature_script}"
            """
        )
    )
    runner.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["FAKE_EXIT_INFO"] = str(tmp_path / "exit-info.txt")
    try:
        return subprocess.run(
            ["bash", str(runner)],
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )
    finally:
        sniffer_proc.terminate()
        try:
            sniffer_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            sniffer_proc.kill()
            sniffer_proc.wait(timeout=5)


def test_crash_verifier_falls_back_to_older_matching_exit_info_pid(tmp_path):
    sig_script = tmp_path / "check_signature.py"
    sig_script.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import sys

            if sys.argv[2] == "1000":
                print("MATCH")
                raise SystemExit(0)
            print("NO_MATCH")
            raise SystemExit(1)
            """
        )
    )
    sig_script.chmod(0o755)

    result = _run_crash_verifier(tmp_path, sig_script)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Crash signature matched exit-info PID=1000" in result.stdout
    assert "Candidate PIDs (newest first): 2000 1000" in result.stdout
    assert "SUCCESS: Exploit verified - app is VULNERABLE" in result.stdout


def test_crash_verifier_reports_all_candidate_pid_mismatches(tmp_path):
    sig_script = tmp_path / "check_signature.py"
    sig_script.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            print("NO_MATCH")
            raise SystemExit(1)
            """
        )
    )
    sig_script.chmod(0o755)

    result = _run_crash_verifier(tmp_path, sig_script)

    assert result.returncode == 1
    assert (
        "Crash signature not found in sniffer log for exit-info PID(s): 2000 1000."
        in result.stdout
    )
    assert "PID=2000 Detail: NO_MATCH" in result.stdout
    assert "PID=1000 Detail: NO_MATCH" in result.stdout
