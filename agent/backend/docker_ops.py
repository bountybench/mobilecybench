import os
import shlex
import time
from functools import lru_cache

# Handle imports from moved mcp files
from agent.backend.docker_setup import HOST_ADB_SERVER, get_kali
from tools.token_truncator import TokenTruncator
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


@lru_cache(maxsize=1)
def get_token_truncator() -> TokenTruncator:
    """Get or create the global token truncator instance."""
    model = os.getenv("MODEL", "gpt-5-2025-08-07")
    max_tokens = int(os.getenv("MAX_KALI_MESSAGE_TOKENS", "8192"))

    t = TokenTruncator(model=model, max_tokens=max_tokens)
    logger.info("TokenTruncator initialized model=%s max_tokens=%s", model, max_tokens)
    return t


def get_ui_state() -> dict:
    """
    Get current UI state with all interactive elements from the Android emulator.
    Returns UI elements with coordinates for interaction.
    """
    from agent.backend.ui_connection import get_ui_state as _get_ui_state

    return _get_ui_state()


def execute_command_internal(command: str) -> str:
    """
    Internal helper function that executes commands and returns truncated command output.
    """
    container = get_kali()
    start_dir = os.getenv("START_DIR", "/app")

    # Determine if the command is an ADB command
    if command.strip().startswith("adb"):
        # Check if ADB command is allowed
        if not is_adb_command_allowed(command):
            raise Exception("This ADB command is not allowed.")

        # Use retry function for ADB commands
        label = "ADB Command"
        try:
            exit_code, output = execute_adb_command_with_retry(command, start_dir)
            combined_output = output
        except Exception as e:
            # Provide clear error message for connection issues
            error_msg = str(e)
            if "no devices/emulators found" in error_msg.lower():
                error_msg += (
                    "\n\nNOTE: This appears to be an ADB connection issue. "
                    "The emulator may still be running. The system attempted to reconnect automatically."
                )
            logger.error(f"ADB command failed: {error_msg}")
            raise Exception(error_msg)
    else:
        # Non-ADB command - execute normally
        full_cmd = f"cd {start_dir} && {command}"
        label = "Command"

        # Safely quote the entire command for bash -c execution inside Docker
        result = container.exec_run(
            f"bash -c {shlex.quote(full_cmd)}", stdout=True, stderr=True
        )
        exit_code = result.exit_code
        output = result.output.decode("utf-8", errors="replace")
        combined_output = output

    # Separate header and body for proper truncation
    header = f"{label}: {command}\nExit Code: {exit_code}\nOutput:\n"

    truncator = get_token_truncator()
    header_tokens = truncator.count_tokens(header)
    body_budget = max(0, truncator.max_tokens - header_tokens)

    if body_budget <= 0:
        truncated_body = "[TRUNCATED]"
    else:
        tr = truncator.truncate_output(combined_output, budget=body_budget)
        if tr.was_truncated:
            logger.info(
                "Kali output truncated: %s -> %s tokens (kept=%s, removed=%s, method=%s)",
                tr.original_tokens,
                tr.final_tokens,
                tr.content_tokens_kept,
                tr.tokens_removed_from_original,
                tr.truncation_method,
            )
        truncated_body = tr.truncated_output

    # formatted and truncated command output
    truncated_response = header + truncated_body

    return truncated_response
