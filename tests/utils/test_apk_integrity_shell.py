"""Shell-level tests for utils/verify/apk_integrity.sh.

These tests stub `adb` (and `sleep`) so the retry loop can be exercised
without a real device. They cover:

  * happy path (on-device sha256sum returns the expected digest immediately);
  * recovery from a transient adbd restart (first N adb invocations fail,
    then succeed) - the regression that commit `7234dd4e`'s symmetric fix
    addressed for the crash buffer but left open for APK pull;
  * permanent failure (adb keeps failing) -> verifier_error / exit 2;
  * tamper detection (pull succeeds but content hash != baseline) -> fail / exit 1.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APK_INTEGRITY = REPO_ROOT / "utils" / "verify" / "apk_integrity.sh"
VERIFIER_COMMON = REPO_ROOT / "utils" / "verify" / "verifier_common.sh"


def _write_fake_bin(
    tmp_path: Path,
    *,
    adb_script: str,
    fast_sleep: bool = True,
) -> Path:
    """Lay down stub adb (+ optionally a no-op sleep) on a private PATH."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    adb = fake_bin / "adb"
    adb.write_text(adb_script)
    adb.chmod(0o755)

    if fast_sleep:
        sleep = fake_bin / "sleep"
        sleep.write_text("#!/usr/bin/env bash\nexit 0\n")
        sleep.chmod(0o755)

    return fake_bin


def _runner(tmp_path: Path, pkg: str, hash_file: Path) -> Path:
    runner = tmp_path / "run_verify.sh"
    runner.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            source "{VERIFIER_COMMON}"
            source "{APK_INTEGRITY}"
            verify_apk_integrity "{pkg}" "{hash_file}"
            """
        )
    )
    runner.chmod(0o755)
    return runner


def _invoke(
    tmp_path: Path, fake_bin: Path, runner: Path
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["FAKE_STATE_DIR"] = str(tmp_path)
    return subprocess.run(
        ["bash", str(runner)],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_on_device_hash_matches_baseline(tmp_path):
    expected = "a" * 64
    hash_file = tmp_path / "baseline.sha256"
    hash_file.write_text(expected + "\n")

    adb_script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        # wait-for-device: always OK.
        if [ "${{1:-}}" = "wait-for-device" ]; then exit 0; fi

        # pm path: return a plausible /data/app path.
        if [ "${{1:-}}" = "shell" ] && [ "${{2:-}}" = "pm" ] && [ "${{3:-}}" = "path" ]; then
            echo "package:/data/app/~~abc==/com.test-xyz==/base.apk"
            exit 0
        fi

        # On-device sha256sum: return the baseline hash.
        if [ "${{1:-}}" = "shell" ] && [ "${{2:-}}" = "sh" ]; then
            echo "{expected}  /data/app/~~abc==/com.test-xyz==/base.apk"
            exit 0
        fi

        echo "unexpected adb invocation: $*" >&2
        exit 99
        """
    )
    fake_bin = _write_fake_bin(tmp_path, adb_script=adb_script)
    runner = _runner(tmp_path, "com.test", hash_file)

    result = _invoke(tmp_path, fake_bin, runner)
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Tamper detection: hash mismatch must still be a hard fail (exit 1).
# ---------------------------------------------------------------------------


def test_hash_mismatch_calls_fail_not_verifier_error(tmp_path):
    expected = "a" * 64
    actual = "b" * 64
    hash_file = tmp_path / "baseline.sha256"
    hash_file.write_text(expected + "\n")

    adb_script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        if [ "${{1:-}}" = "wait-for-device" ]; then exit 0; fi
        if [ "${{1:-}}" = "shell" ] && [ "${{2:-}}" = "pm" ] && [ "${{3:-}}" = "path" ]; then
            echo "package:/data/app/~~abc==/com.test-xyz==/base.apk"
            exit 0
        fi
        if [ "${{1:-}}" = "shell" ] && [ "${{2:-}}" = "sh" ]; then
            echo "{actual}  /data/app/~~abc==/com.test-xyz==/base.apk"
            exit 0
        fi
        echo "unexpected adb invocation: $*" >&2
        exit 99
        """
    )
    fake_bin = _write_fake_bin(tmp_path, adb_script=adb_script)
    runner = _runner(tmp_path, "com.test", hash_file)

    result = _invoke(tmp_path, fake_bin, runner)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "APK integrity mismatch" in result.stdout
    assert "reward hack" in result.stdout


# ---------------------------------------------------------------------------
# Recovery: adbd is mid-restart for the first two attempts (sha256sum returns
# garbage and `adb pull` fails), then settles. The retry loop should succeed.
# ---------------------------------------------------------------------------


def test_retry_recovers_from_transient_adbd_restart(tmp_path):
    apk_bytes = b"fake apk payload for hashing"
    expected = hashlib.sha256(apk_bytes).hexdigest()
    hash_file = tmp_path / "baseline.sha256"
    hash_file.write_text(expected + "\n")

    apk_payload = tmp_path / "good.apk"
    apk_payload.write_bytes(apk_bytes)

    # First 2 adb-pull attempts fail; sha256sum always returns invalid (no
    # 64-hex output) so the function falls through to the pull path.
    adb_script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        STATE="$FAKE_STATE_DIR/pull_attempts"
        if [ "${{1:-}}" = "wait-for-device" ]; then exit 0; fi

        if [ "${{1:-}}" = "shell" ] && [ "${{2:-}}" = "pm" ] && [ "${{3:-}}" = "path" ]; then
            echo "package:/data/app/~~abc==/com.test-xyz==/base.apk"
            exit 0
        fi

        # Force the pull-fallback branch by returning empty from on-device hash.
        if [ "${{1:-}}" = "shell" ] && [ "${{2:-}}" = "sh" ]; then
            exit 1
        fi

        if [ "${{1:-}}" = "pull" ]; then
            n=0
            [ -f "$STATE" ] && n=$(cat "$STATE")
            n=$((n + 1))
            echo "$n" > "$STATE"
            if [ "$n" -le 2 ]; then
                echo "adb: device offline" >&2
                exit 1
            fi
            cp "{apk_payload}" "$3"
            exit 0
        fi

        echo "unexpected adb invocation: $*" >&2
        exit 99
        """
    )
    fake_bin = _write_fake_bin(tmp_path, adb_script=adb_script)
    runner = _runner(tmp_path, "com.test", hash_file)

    result = _invoke(tmp_path, fake_bin, runner)
    assert result.returncode == 0, result.stdout + result.stderr

    # Confirm the retry loop actually retried (>= 3 invocations of `adb pull`).
    state = (tmp_path / "pull_attempts").read_text().strip()
    assert int(state) >= 3, f"expected >=3 pull attempts, got {state}"


# ---------------------------------------------------------------------------
# Permanent failure: device never recovers -> verifier_error (exit 2) only
# after retries exhaust. Must not turn into exit 1 (which would be a security
# regression: tamper-vs-flake confusion).
# ---------------------------------------------------------------------------


def test_permanent_adb_failure_emits_verifier_error_after_retries(tmp_path):
    expected = "a" * 64
    hash_file = tmp_path / "baseline.sha256"
    hash_file.write_text(expected + "\n")

    adb_script = textwrap.dedent(
        """\
        #!/usr/bin/env bash
        STATE="$FAKE_STATE_DIR/all_attempts"
        n=0
        [ -f "$STATE" ] && n=$(cat "$STATE")
        n=$((n + 1))
        echo "$n" > "$STATE"

        if [ "${1:-}" = "wait-for-device" ]; then exit 0; fi

        if [ "${1:-}" = "shell" ] && [ "${2:-}" = "pm" ] && [ "${3:-}" = "path" ]; then
            echo "package:/data/app/~~abc==/com.test-xyz==/base.apk"
            exit 0
        fi

        # Both on-device hash and pull always fail.
        exit 1
        """
    )
    fake_bin = _write_fake_bin(tmp_path, adb_script=adb_script)
    runner = _runner(tmp_path, "com.test", hash_file)

    result = _invoke(tmp_path, fake_bin, runner)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "after 5 attempts" in result.stdout
    # Don't false-positive a tamper claim when the device just isn't reachable.
    assert "reward hack" not in result.stdout
