import json
import os
import shlex
from functools import lru_cache

from command_helpers import is_adb_command_allowed
from docker_setup import HOST_ADB_SERVER, get_kali
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from ui_connection import get_ui_state

from tools.token_truncator import TokenTruncator
from utils.logger import logger

"""
MCP Server Tools:
- execute_command(): Pure text output (calls _execute_command_internal)
- get_current_ui_state(): UI elements only (calls get_ui_state from ui_connection.py)  
- execute_command_with_ui_state(): Command output + UI state (combines both)
"""


def _get_allowed_tools() -> list:
    """Get the list of allowed tools from environment variable."""
    allowed_tools_json = os.getenv("ALLOWED_TOOLS")
    if not allowed_tools_json:
        return [
            "execute_command",
            "get_current_ui_state",
            "execute_command_with_ui_state",
        ]  # Default: all tools

    try:
        allowed_tools = json.loads(allowed_tools_json)
        return allowed_tools
    except json.JSONDecodeError:
        logger.error(
            "Failed to parse ALLOWED_TOOLS environment variable, allowing all tools"
        )
        return [
            "execute_command",
            "get_current_ui_state",
            "execute_command_with_ui_state",
        ]


mcp = FastMCP(name="Mobile Cyber MCP", stateless_http=True)

# Get allowed tools once at startup
ALLOWED_TOOLS = _get_allowed_tools()
logger.info(f"Registering tools: {ALLOWED_TOOLS}")


@lru_cache(maxsize=1)
def _get_token_truncator() -> TokenTruncator:
    """Get or create the global token truncator instance.

    Returns:
        TokenTruncator instance configured for the current model

    Raises:
        Exception: If TokenTruncator initialization fails (fail fast)
    """
    # Get configuration from environment variables (set by runner.py)
    model = os.getenv("MODEL", "gpt-5-2025-08-07")
    max_tokens = int(os.getenv("MAX_KALI_MESSAGE_TOKENS", "8192"))

    t = TokenTruncator(model=model, max_tokens=max_tokens)
    logger.info("TokenTruncator initialized model=%s max_tokens=%s", model, max_tokens)
    return t


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    """Health check endpoint for container orchestration"""
    return PlainTextResponse("OK")


def _execute_command_internal(command: str) -> str:
    """
    Internal helper function that executes commands and returns truncated command output.
    """
    container = get_kali()
    start_dir = os.getenv("START_DIR", "/app/codebase")

    # Determine if the command is an ADB command
    if command.strip().startswith("adb"):
        # Prefix ADB server socket export and change to start directory
        if not is_adb_command_allowed(command):
            raise Exception("This ADB command is not allowed.")
        full_cmd = f"cd {start_dir} && export ADB_SERVER_SOCKET=tcp:{HOST_ADB_SERVER} && {command}"
        label = "ADB Command"
    else:
        # Change to start directory before executing command
        full_cmd = f"cd {start_dir} && {command}"
        label = "Command"

    # Safely quote the entire command for bash -c execution inside Docker
    result = container.exec_run(
        f"bash -c {shlex.quote(full_cmd)}", stdout=True, stderr=True
    )
    output = result.output.decode("utf-8", errors="replace")

    # Separate header and body for proper truncation
    header = f"{label}: {command}\nExit Code: {result.exit_code}\nOutput:\n"

    truncator = _get_token_truncator()
    header_tokens = truncator.count_tokens(header)
    body_budget = max(0, truncator.max_tokens - header_tokens)

    if body_budget <= 0:
        truncated_body = "[TRUNCATED]"
    else:
        tr = truncator.truncate_output(output, budget=body_budget)
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


# Conditionally register execute_command tool
if "execute_command" in ALLOWED_TOOLS:

    @mcp.tool(
        description="Execute terminal command and return text output only (no UI state). Use for security scans, file operations, and system commands."
    )
    def execute_command(command: str) -> str:
        """
        Execute command and return only text output - no UI state included.
        Optimized for security testing, file operations, and system commands.
        """
        try:
            return _execute_command_internal(command)
        except Exception as e:
            return f"Error: {str(e)}"


# Conditionally register get_current_ui_state tool
if "get_current_ui_state" in ALLOWED_TOOLS:

    @mcp.tool(
        description="Get current UI elements from Android emulator screen without executing any command."
    )
    def get_current_ui_state() -> dict:
        """
        Get current UI state with all interactive elements from the Android emulator.
        Returns UI elements with coordinates for interaction.
        """
        try:
            return get_ui_state()
        except Exception as e:
            return {"error": f"Failed to get UI state: {str(e)}", "ui_elements": []}


# Conditionally register execute_command_with_ui_state tool
if "execute_command_with_ui_state" in ALLOWED_TOOLS:

    @mcp.tool(
        description="Execute terminal command and include current UI state. Use when you need both command output and UI context."
    )
    def execute_command_with_ui_state(command: str) -> dict:
        """
        Execute command and return both text output and current UI state.
        Use when you need to see the effect of commands on the UI or for UI interaction commands.
        """
        try:
            command_output = _execute_command_internal(command)
            ui_data = get_ui_state()
            ui_data["result"] = command_output
            return ui_data
        except Exception as e:
            ui_data = get_ui_state()
            ui_data["result"] = f"Error: {str(e)}"
            return ui_data


if __name__ == "__main__":
    mcp.run(transport="http", port=8000, host="0.0.0.0")
