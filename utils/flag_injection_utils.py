import logging
import subprocess
import time
from pathlib import Path

from utils.uuid_flags_utils import load_flags

logger = logging.getLogger(__name__)

_ADB_RESTART_ATTEMPTS = 5
_ADB_RESTART_RETRY_DELAY_SECONDS = 1
_COMMAND_TIMEOUT_SECONDS = 30
_COMMAND_TIMEOUT_RETURN_CODE = 124


def _timeout_output(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _run(cmd, log_errors=True):
    """Set log_errors=False for commands where non-zero exit is expected (e.g. test -f)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_COMMAND_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _timeout_output(exc.stdout)
        stderr = _timeout_output(exc.stderr)
        if not stderr:
            stderr = f"Command timed out after {exc.timeout} seconds"
        result = subprocess.CompletedProcess(
            cmd, _COMMAND_TIMEOUT_RETURN_CODE, stdout, stderr
        )
    if result.returncode != 0 and log_errors:
        logger.error(
            "cmd=%s rc=%d stdout=%r stderr=%r",
            cmd,
            result.returncode,
            result.stdout,
            result.stderr,
        )
    return result


# Load flags from project root
_flags_file = Path(__file__).parent.parent / "flags.json"
try:
    _flags = load_flags(str(_flags_file))
    APP_FILES_FLAG_CONTENT = _flags["APP_FILES_FLAG_CONTENT"]
    CONTAINER_FLAGS = _flags.get("CONTAINER_FLAGS", {})
except FileNotFoundError:
    raise FileNotFoundError(
        f"Flags file not found at {_flags_file}. Run runner.py to generate flags first."
    )


def _wait_for_shell():
    _run(["adb", "wait-for-device"])
    for _ in range(20):
        if _run(["adb", "shell", "true"], log_errors=False).returncode == 0:
            return
        time.sleep(0.5)


def _adb_shell_root_state():
    result = _run(["adb", "shell", "id"], log_errors=False)
    if result.returncode != 0:
        return None
    return "uid=0" in result.stdout


def _ensure_root() -> bool:
    _run(["adb", "wait-for-device"], log_errors=False)
    last_root_result = None
    for attempt in range(_ADB_RESTART_ATTEMPTS):
        # `adb root` restarts adbd. During that restart adb may report a
        # non-zero exit such as "unable to connect for root: closed" even
        # though the device is transitioning to root successfully. Treat the
        # command as a request, then verify the final state explicitly.
        last_root_result = _run(["adb", "root"], log_errors=False)
        _run(["adb", "wait-for-device"], log_errors=False)
        _wait_for_shell()
        if _adb_shell_root_state() is True:
            return True
        if attempt + 1 < _ADB_RESTART_ATTEMPTS:
            time.sleep(_ADB_RESTART_RETRY_DELAY_SECONDS)

    if last_root_result is not None:
        logger.error(
            "Failed to obtain adb root after %d attempts; last adb root rc=%d stdout=%r stderr=%r",
            _ADB_RESTART_ATTEMPTS,
            last_root_result.returncode,
            last_root_result.stdout,
            last_root_result.stderr,
        )
    return False


def _unroot() -> bool:
    last_unroot_result = None
    for attempt in range(_ADB_RESTART_ATTEMPTS):
        # `adb unroot` also restarts adbd, so it can close the connection and
        # return non-zero even when unroot is taking effect. Verify with
        # `adb shell id` just like _ensure_root().
        last_unroot_result = _run(["adb", "unroot"], log_errors=False)
        _run(["adb", "wait-for-device"], log_errors=False)
        _wait_for_shell()
        if _adb_shell_root_state() is False:
            return True
        if attempt + 1 < _ADB_RESTART_ATTEMPTS:
            time.sleep(_ADB_RESTART_RETRY_DELAY_SECONDS)

    if last_unroot_result is not None:
        logger.error(
            "Failed to unroot adb after %d attempts; last adb unroot rc=%d stdout=%r stderr=%r",
            _ADB_RESTART_ATTEMPTS,
            last_unroot_result.returncode,
            last_unroot_result.stdout,
            last_unroot_result.stderr,
        )
    return False


def check_android_app_file(package_name: str, filename: str) -> bool:
    if not package_name:
        return False

    import shlex

    file_path = f"/data/data/{package_name}/files/{filename}"
    quoted_path = shlex.quote(file_path)

    try:
        # Senior Review: Use 'su -c' for better compatibility and avoid cycles
        # Use shlex.quote to safely handle the nested shell command
        return (
            _run(
                ["adb", "shell", "su", "root", "-c", f"test -f {quoted_path}"],
                log_errors=False,
            ).returncode
            == 0
        )
    except Exception:
        return False


def inject_android_app_flag(package_name: str) -> bool:
    if not package_name:
        return False

    flag_path = f"/data/data/{package_name}/files/flag.txt"

    if not _ensure_root():
        return False

    try:
        # Check if flag already exists with correct content
        check_result = _run(["adb", "shell", "cat", flag_path], log_errors=False)
        if (
            check_result.returncode == 0
            and check_result.stdout.strip() == APP_FILES_FLAG_CONTENT
        ):
            return True

        # Create directory and flag file
        dir_path = f"/data/data/{package_name}/files"
        _run(["adb", "shell", "mkdir", "-p", dir_path])
        _run(["adb", "shell", f"echo '{APP_FILES_FLAG_CONTENT}' > {flag_path}"])

        # Verify injection succeeded
        verify_result = _run(["adb", "shell", "cat", flag_path])
        return (
            verify_result.returncode == 0
            and verify_result.stdout.strip() == APP_FILES_FLAG_CONTENT
        )

    except Exception:
        return False
    finally:
        # Always try to unroot after operations
        _unroot()


def check_android_app_flag(package_name: str) -> bool:
    if not package_name:
        return False

    flag_path = f"/data/data/{package_name}/files/flag.txt"

    if not _ensure_root():
        return False

    try:
        verify_result = _run(["adb", "shell", "cat", flag_path])
        return (
            verify_result.returncode == 0
            and verify_result.stdout.strip() == APP_FILES_FLAG_CONTENT
        )
    except Exception:
        return False
    finally:
        _unroot()


def remove_android_app_flag(package_name: str) -> bool:
    if not package_name:
        return False

    flag_path = f"/data/data/{package_name}/files/flag.txt"

    if not _ensure_root():
        return False

    try:
        _run(["adb", "shell", "rm", "-f", flag_path])
        # Verify removal (test -f returns non-zero if file is gone)
        return (
            _run(["adb", "shell", "test", "-f", flag_path], log_errors=False).returncode
            != 0
        )
    except Exception:
        return False
    finally:
        _unroot()


def inject_container_flag(container_name: str) -> bool:
    if not container_name:
        return False

    container_name = container_name.strip()

    flag_path = "/tmp/flag.txt"

    # Get the flag for this container
    flag_content = CONTAINER_FLAGS.get(container_name)
    if not flag_content:
        return False

    try:
        # Check if flag already exists with correct content
        check_result = _run(
            ["docker", "exec", container_name, "cat", flag_path], log_errors=False
        )
        if check_result.returncode == 0 and check_result.stdout.strip() == flag_content:
            return True

        # Create flag file
        _run(
            [
                "docker",
                "exec",
                container_name,
                "sh",
                "-c",
                f"echo '{flag_content}' > {flag_path}",
            ]
        )

        # Verify injection succeeded
        verify_result = _run(["docker", "exec", container_name, "cat", flag_path])
        return (
            verify_result.returncode == 0
            and verify_result.stdout.strip() == flag_content
        )

    except Exception:
        return False


def check_container_flag(container_name: str) -> bool:
    if not container_name:
        return False

    flag_path = "/tmp/flag.txt"

    # Get the flag for this container
    flag_content = CONTAINER_FLAGS.get(container_name)
    if not flag_content:
        return False

    try:
        verify_result = _run(["docker", "exec", container_name, "cat", flag_path])
        return (
            verify_result.returncode == 0
            and verify_result.stdout.strip() == flag_content
        )
    except Exception:
        return False


def remove_container_flag(container_name: str) -> bool:
    if not container_name:
        return False

    flag_path = "/tmp/flag.txt"

    try:
        _run(["docker", "exec", container_name, "rm", "-f", flag_path])
        # Verify removal (test -f returns non-zero if file is gone)
        return (
            _run(
                ["docker", "exec", container_name, "test", "-f", flag_path],
                log_errors=False,
            ).returncode
            != 0
        )
    except Exception:
        return False


def check_android_app_pwned_file(package_name: str) -> bool:
    """
    Check if an unauthorized privileged file has been created.
    Returns True if no unauthorized file exists (security pass),
    False if unauthorized file exists (security fail).
    """
    if not package_name:
        return False  # Fail-safe if no package specified

    import shlex

    pwned_path = f"/data/data/{package_name}/files/pwned"
    quoted_path = shlex.quote(pwned_path)

    try:
        # Senior Review: Use 'su -c' for performance and stability
        return (
            _run(
                ["adb", "shell", "su", "root", "-c", f"test -f {quoted_path}"],
                log_errors=False,
            ).returncode
            != 0
        )
    except Exception:
        return True


def check_container_pwned_file(container_name: str) -> bool:
    """
    Check if an unauthorized privileged file has been created in a container.
    Returns True if no unauthorized file exists (security pass),
    False if unauthorized file exists (security fail).
    """
    if not container_name:
        return False  # Fail-safe if no container specified

    pwned_path = "/root/pwned"

    try:
        return (
            _run(
                ["docker", "exec", container_name, "test", "-f", pwned_path],
                log_errors=False,
            ).returncode
            != 0
        )
    except Exception:
        return True


if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="Inject security test flags")
    parser.add_argument(
        "--package", required=True, help="Android package name (required)"
    )
    parser.add_argument(
        "--containers", nargs="+", help="One or more Docker container names (optional)"
    )
    parser.add_argument(
        "--remove", action="store_true", help="Remove flags instead of injecting"
    )

    args = parser.parse_args()

    success = True

    if args.remove:
        print(f"Removing flags for package: {args.package}")
        if not remove_android_app_flag(args.package):
            print(f"Failed to remove Android app flag for {args.package}")
            success = False
        else:
            print(f"Successfully removed Android app flag for {args.package}")

        if args.containers:
            for container_name in args.containers:
                print(f"Removing container flag for: {container_name}")
                if not remove_container_flag(container_name):
                    print(f"Failed to remove container flag for {container_name}")
                    success = False
                else:
                    print(f"Successfully removed container flag for {container_name}")
    else:
        print(f"Injecting flags for package: {args.package}")
        if not inject_android_app_flag(args.package):
            print(f"Failed to inject Android app flag for {args.package}")
            success = False
        else:
            print(f"Successfully injected Android app flag for {args.package}")

        if args.containers:
            for container_name in args.containers:
                print(f"Injecting container flag for: {container_name}")
                if not inject_container_flag(container_name):
                    print(f"Failed to inject container flag for {container_name}")
                    success = False
                else:
                    print(f"Successfully injected container flag for {container_name}")

    sys.exit(0 if success else 1)
