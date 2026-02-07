import os
import re
import shlex
import time
from functools import lru_cache

from agent.backend.docker_setup import HOST_ADB_SERVER, get_kali
from utils.logger import logger


def load_blocked_patterns():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(script_dir, "blocked_adb_patterns.txt")

    if not os.path.exists(path):
        return set()  # empty set if file doesn't exist

    with open(path, "r") as f:
        return {line.strip() for line in f if line.strip()}


# cache blocked patterns to ensure we don't read the file multiple times
BLOCKED_PATTERNS = load_blocked_patterns()


def is_adb_command_allowed(command, return_match=False):
    # look for one more more slashes / and replace with single slash
    # this is to protect against commands like: "/system/xbin/su and //system///xbin///su"
    clean_cmd = re.sub(r"/+", "/", command.strip())
    normalized_cmd = " ".join(clean_cmd.lower().split())

    for pattern in BLOCKED_PATTERNS:
        # take the literal lowered pattern and escape so that special regex characters are not interpreted
        escaped_pattern = re.escape(pattern.lower())
        # \b in regex makes sure this is a standalone word match, so "root" doesn't trigger in "grassroots" but only when it is "adb root"
        if re.search(rf"\b{escaped_pattern}\b", normalized_cmd):
            if return_match:
                return False, pattern
            return False
    return True

# We check exploit.sh if there are any blocked patterns in it, and if there are, we report the line number and the matched pattern for each violation
def check_shell_script(filepath):
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")
    
    violations = []
    
    with open(filepath, "r") as f:
        for line_num, line in enumerate(f, start=1):
            stripped_line = line.strip()
            if not stripped_line or stripped_line.startswith('#'):
                continue
            
            is_allowed, matched_pattern = is_adb_command_allowed(stripped_line, return_match=True)
            
            if not is_allowed:
                violations.append({
                    'line_number': line_num,
                    'line_content': stripped_line,
                    'matched_pattern': matched_pattern
                })
    
    is_allowed = len(violations) == 0
    with open("exploit_sh_verify.log", "w") as log_file:
        log_file.write("=" * 80 + "\n")
        log_file.write(f"ALLOWED: {is_allowed}\n")
        for violation in violations:
            log_file.write(f"Line {violation['line_number']}: {violation['line_content']} (matched pattern: {violation['matched_pattern']})\n")
        log_file.write("=" * 80 + "\n")

    print("=" * 80 + "\n")
    print(f"ALLOWED: {is_allowed}\n")
    for violation in violations:
        print(f"Line {violation['line_number']}: {violation['line_content']} (matched pattern: {violation['matched_pattern']})\n")
    print("=" * 80 + "\n")
    return is_allowed, violations


def execute_adb_command_with_retry(
    command: str, start_dir: str, max_retries: int = 2, timeout: int = 300
) -> tuple:
    """
    Execute an ADB command with automatic retry on connection errors.

    Args:
        command: ADB command to execute (must start with 'adb')
        start_dir: Directory to execute command from
        max_retries: Maximum number of retry attempts
        timeout: Maximum time in seconds to wait for command completion (default: 300 / 5 min)

    Returns:
        Tuple of (exit_code, stdout_string, stderr_string)

    Raises:
        Exception: If command fails after all retries
    """
    container = get_kali()
    # Wrap command with timeout to prevent hanging
    full_cmd_base = f"cd {start_dir} && export ADB_SERVER_SOCKET=tcp:{HOST_ADB_SERVER} && timeout {timeout}s {command}"
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

            # Check for timeout (exit code 124)
            if exit_code == 124:
                logger.warning(f"ADB command timed out after {timeout}s: {command}")
                return (
                    exit_code,
                    f"[COMMAND TIMED OUT after {timeout} seconds]\n{stdout}",
                    stderr,
                )

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


def execute_command_internal(command: str, timeout: int = 300) -> str:
    """
    Internal helper function that executes commands and returns truncated command output.

    Args:
        command: The shell command to execute
        timeout: Maximum time in seconds to wait for command completion (default: 300 / 5 min)
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
            exit_code, stdout, stderr = execute_adb_command_with_retry(
                command, start_dir, timeout=timeout
            )
            combined_output = stdout + stderr
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
        # Non-ADB command - execute normally with timeout
        # Use the `timeout` command to enforce time limit (available in most Linux containers)
        full_cmd = (
            f"cd {start_dir} && timeout {timeout}s bash -c {shlex.quote(command)}"
        )
        label = "Command"

        # Safely quote the entire command for bash -c execution inside Docker
        result = container.exec_run(
            f"bash -c {shlex.quote(full_cmd)}", stdout=True, stderr=True
        )
        exit_code = result.exit_code
        output = result.output.decode("utf-8", errors="replace")

        # Check for timeout (exit code 124 is timeout's signal)
        if exit_code == 124:
            combined_output = f"[COMMAND TIMED OUT after {timeout} seconds]\n{output}"
            logger.warning(f"Command timed out after {timeout}s: {command}")
        else:
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
