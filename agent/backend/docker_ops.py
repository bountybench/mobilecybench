import os
import shlex
import sys
from functools import lru_cache

# Handle imports from agent/mcp which might be in path or not
try:
    from agent.mcp.command_helpers import (
        execute_adb_command_with_retry,
        is_adb_command_allowed,
    )
    from agent.mcp.docker_setup import get_kali
    from agent.mcp.ui_connection import get_ui_state as _get_ui_state
except ImportError:
    # If standard import fails, try adding agent/mcp to path
    mcp_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp")
    if mcp_path not in sys.path:
        sys.path.append(mcp_path)

    from command_helpers import execute_adb_command_with_retry, is_adb_command_allowed
    from docker_setup import get_kali
    from ui_connection import get_ui_state as _get_ui_state

from tools.token_truncator import TokenTruncator
from utils.logger import logger


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
