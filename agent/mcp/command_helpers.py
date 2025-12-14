import os
import shlex
import time

from docker_setup import HOST_ADB_SERVER, get_kali

from utils.logger import logger


def is_adb_command_allowed(command):
    command = " ".join(command.strip().split())
    # Get the directory where this script is located
    script_dir = os.path.dirname(os.path.abspath(__file__))
    blocked_patterns_path = os.path.join(script_dir, "blocked_adb_patterns.txt")

    with open(blocked_patterns_path, "r") as f:
        blocked_patterns = f.read().splitlines()
    for pattern in blocked_patterns:
        if pattern in command:
            return False
    return True


def execute_adb_command_with_retry(
    command: str, start_dir: str, max_retries: int = 2
) -> tuple:
    """
    Execute an ADB command with automatic retry on connection errors.

    Args:
        command: ADB command to execute (must start with 'adb')
        start_dir: Directory to execute command from
        max_retries: Maximum number of retry attempts

    Returns:
        Tuple of (exit_code, stdout_string, stderr_string)

    Raises:
        Exception: If command fails after all retries
    """
    container = get_kali()
    full_cmd_base = (
        f"cd {start_dir} && export ADB_SERVER_SOCKET=tcp:{HOST_ADB_SERVER} && {command}"
    )
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            result = container.exec_run(
                f"bash -c {shlex.quote(full_cmd_base)}",
                stdout=True,
                stderr=True,
                demux=True,
            )

            stdout = (
                result.output[0].decode("utf-8", errors="replace")
                if result.output[0]
                else ""
            )
            stderr = (
                result.output[1].decode("utf-8", errors="replace")
                if result.output[1]
                else ""
            )
            exit_code = result.exit_code

            # Check for "no devices/emulators found" error
            # Combine stdout and stderr for checking errors
            combined_output = (stdout + stderr).lower()
            is_no_devices = "no devices/emulators found" in combined_output
            has_daemon_msg = "daemon" in combined_output and (
                "not running" in combined_output or "started" in combined_output
            )

            # If we get "no devices" with daemon messages, it's likely a connection issue
            if is_no_devices and has_daemon_msg and attempt < max_retries:
                logger.warning(
                    f"ADB connection issue detected (attempt {attempt + 1}/{max_retries + 1}), retrying..."
                )
                # Try to reconnect by starting server and waiting
                reconnect_cmd = f"cd {start_dir} && export ADB_SERVER_SOCKET=tcp:{HOST_ADB_SERVER} && adb -a start-server && sleep 1"
                container.exec_run(
                    f"bash -c {shlex.quote(reconnect_cmd)}",
                    stdout=True,
                    stderr=True,
                )
                time.sleep(1)
                continue

            # Return result (success or other error)
            return exit_code, stdout, stderr

        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                logger.warning(
                    f"ADB command failed (attempt {attempt + 1}/{max_retries + 1}): {e}, retrying..."
                )
                time.sleep(1)
                continue
            # Last attempt failed, raise the exception
            raise

    # Should not reach here, but if we do, raise last exception
    if last_exception:
        raise last_exception
    raise Exception(f"ADB command failed after {max_retries + 1} attempts: {command}")
