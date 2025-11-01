#!/usr/bin/env python3

import json
import os
import shlex
import sys
from functools import lru_cache
from pathlib import Path

# Add project root to sys.path to enable imports
# (when Claude Desktop launches the script directly)
# This must happen before imports that depend on project modules
script_dir = Path(__file__).parent
project_root = script_dir.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

os.chdir(str(project_root))  # makes sure logs go to project root

from fastmcp import FastMCP  # noqa: E402

from tools.token_truncator import TokenTruncator  # noqa: E402



def _lazy_import_docker():
    """Lazy import of Docker-related modules to avoid startup failures."""
    try:
        from agent.mcp.docker_setup import HOST_ADB_SERVER, get_kali
        from agent.mcp.ui_connection import get_ui_state

        return HOST_ADB_SERVER, get_kali, get_ui_state
    except Exception as e:
        raise RuntimeError(
            "Docker connection failed. Please ensure Docker is running and the Kali container is available."
        ) from e


def _get_allowed_tools() -> list:
    allowed_tools_json = os.getenv("ALLOWED_TOOLS")
    if not allowed_tools_json:
        return [
            "execute_command",
            "get_current_ui_state",
            "execute_command_with_ui_state",
        ]

    try:
        allowed_tools = json.loads(allowed_tools_json)
        return allowed_tools
    except json.JSONDecodeError:
        return [
            "execute_command",
            "get_current_ui_state",
            "execute_command_with_ui_state",
        ]


mcp = FastMCP(name="Mobile Cyber MCP")

ALLOWED_TOOLS = _get_allowed_tools()


@lru_cache(maxsize=1)
def _get_token_truncator() -> TokenTruncator:
    # TokenTruncator doesn't support anthropic models - just going with the default settings
    model = os.getenv("MODEL", "gpt-5-2025-08-07")
    max_tokens = int(os.getenv("MAX_KALI_MESSAGE_TOKENS", "8192"))

    t = TokenTruncator(model=model, max_tokens=max_tokens)
    return t


def _execute_command_internal(command: str) -> str:
    HOST_ADB_SERVER, get_kali, _ = _lazy_import_docker()

    container = get_kali()
    start_dir = os.getenv("START_DIR", "/app/codebase")

    if command.strip().startswith("adb"):
        full_cmd = f"cd {start_dir} && export ADB_SERVER_SOCKET=tcp:{HOST_ADB_SERVER} && {command}"
        label = "ADB Command"
    else:
        full_cmd = f"cd {start_dir} && {command}"
        label = "Command"

    result = container.exec_run(
        f"bash -c {shlex.quote(full_cmd)}", stdout=True, stderr=True
    )
    output = result.output.decode("utf-8", errors="replace")

    header = f"{label}: {command}\nExit Code: {result.exit_code}\nOutput:\n"

    truncator = _get_token_truncator()
    header_tokens = truncator.count_tokens(header)
    body_budget = max(0, truncator.max_tokens - header_tokens)

    if body_budget <= 0:
        truncated_body = "[TRUNCATED]"
    else:
        tr = truncator.truncate_output(output, budget=body_budget)
        truncated_body = tr.truncated_output

    return header + truncated_body


if "execute_command" in ALLOWED_TOOLS:

    @mcp.tool(
        description=(
            "Run a terminal command and return the plain text output. "
            "No UI state is included. Ideal for executing system-level or security-related commands."
        )
    )
    def execute_command(command: str) -> str:
        """Execute command and return only text output - no UI state included."""
        try:
            return _execute_command_internal(command)
        except Exception as e:
            return f"Error: {str(e)}"


if "get_current_ui_state" in ALLOWED_TOOLS:

    @mcp.tool(
        description=(
            "Retrieve a structured snapshot of the current Android emulator UI, "
            "including all visible and interactive elements. "
            "Use this tool when you need UI context without executing any commands."
        )
    )
    def get_current_ui_state() -> dict:
        """Get current UI state with all interactive elements from the Android emulator."""
        try:
            _, _, get_ui_state = _lazy_import_docker()
            return get_ui_state()
        except Exception as e:
            return {"error": f"Failed to get UI state: {str(e)}", "ui_elements": []}


if "execute_command_with_ui_state" in ALLOWED_TOOLS:

    @mcp.tool(
        description=(
            "Execute terminal command and return both "
            "the command's text output and a snapshot of the current UI state. "
            "Use this when you need to correlate command results with on-screen UI elements."
        )
    )
    def execute_command_with_ui_state(command: str) -> dict:
        try:
            command_output = _execute_command_internal(command)
            _, _, get_ui_state = _lazy_import_docker()
            ui_data = get_ui_state()
            ui_data["response"] = command_output
            return ui_data
        except Exception as e:
            try:
                # Try to get UI state even on error
                _, _, get_ui_state = _lazy_import_docker()
                ui_data = get_ui_state()
            except Exception as e:
                ui_data = {
                    "ui_elements": [],
                    "error": f"Failed to get UI state: {str(e)}",
                }
            ui_data["response"] = f"Error: {str(e)}"
            return ui_data


if __name__ == "__main__":
    mcp.run(transport="stdio")
#!/usr/bin/env python3

import json
import os
import shlex
import sys
from functools import lru_cache
from pathlib import Path

# Add project root to sys.path to enable imports
# (when Claude Desktop launches the script directly)
script_dir = Path(__file__).parent
project_root = script_dir.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

os.chdir(str(project_root)) # makes sure logs go to project root
from fastmcp import FastMCP
from tools.token_truncator import TokenTruncator
from utils.logger import logger

def _lazy_import_docker():
    """Lazy import of Docker-related modules to avoid startup failures."""
    try:
        from agent.mcp.docker_setup import HOST_ADB_SERVER, get_kali
        from agent.mcp.ui_connection import get_ui_state
        return HOST_ADB_SERVER, get_kali, get_ui_state
    except Exception as e:
        logger.error(f"Failed to import Docker modules: {e}")
        raise RuntimeError(
            "Docker connection failed. Please ensure Docker is running and the Kali container is available."
        ) from e


def _get_allowed_tools() -> list:
    allowed_tools_json = os.getenv("ALLOWED_TOOLS")
    if not allowed_tools_json:
        return [
            "execute_command",
            "get_current_ui_state",
            "execute_command_with_ui_state",
        ]

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


mcp = FastMCP(name="Mobile Cyber MCP")

ALLOWED_TOOLS = _get_allowed_tools()
logger.info(f"Registering tools for Claude Desktop: {ALLOWED_TOOLS}")


@lru_cache(maxsize=1)
def _get_token_truncator() -> TokenTruncator:
    # TokenTruncator doesn't support anthropic models - just going with the default settings
    model = os.getenv("MODEL", "gpt-5-2025-08-07") 
    max_tokens = int(os.getenv("MAX_KALI_MESSAGE_TOKENS", "8192"))

    t = TokenTruncator(model=model, max_tokens=max_tokens)
    logger.info("TokenTruncator initialized model=%s max_tokens=%s", model, max_tokens)
    return t


def _execute_command_internal(command: str) -> str:
    HOST_ADB_SERVER, get_kali, _ = _lazy_import_docker()

    container = get_kali()
    start_dir = os.getenv("START_DIR", "/app/codebase")

    if command.strip().startswith("adb"):
        full_cmd = f"cd {start_dir} && export ADB_SERVER_SOCKET=tcp:{HOST_ADB_SERVER} && {command}"
        label = "ADB Command"
    else:
        full_cmd = f"cd {start_dir} && {command}"
        label = "Command"

    result = container.exec_run(
        f"bash -c {shlex.quote(full_cmd)}", stdout=True, stderr=True
    )
    output = result.output.decode("utf-8", errors="replace")

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

    return header + truncated_body


if "execute_command" in ALLOWED_TOOLS:
    @mcp.tool(
        description=(
        "Run a terminal command and return the plain text output. "
        "No UI state is included. Ideal for executing system-level or security-related commands."
        )
    )
    def execute_command(command: str) -> str:
        """Execute command and return only text output - no UI state included."""
        try:
            return _execute_command_internal(command)
        except Exception as e:
            return f"Error: {str(e)}"


if "get_current_ui_state" in ALLOWED_TOOLS:
    @mcp.tool(
            description=(
            "Retrieve a structured snapshot of the current Android emulator UI, "
            "including all visible and interactive elements. "
            "Use this tool when you need UI context without executing any commands."
            )
    )
    def get_current_ui_state() -> dict:
        """Get current UI state with all interactive elements from the Android emulator."""
        try:
            _, _, get_ui_state = _lazy_import_docker()
            return get_ui_state()
        except Exception as e:
            return {"error": f"Failed to get UI state: {str(e)}", "ui_elements": []}


if "execute_command_with_ui_state" in ALLOWED_TOOLS:
    @mcp.tool(
        description=(
        "Execute terminal command and return both "
        "the command's text output and a snapshot of the current UI state. "
        "Use this when you need to correlate command results with on-screen UI elements."
        )
    )
    def execute_command_with_ui_state(command: str) -> dict:
        try:
            command_output = _execute_command_internal(command)
            _, _, get_ui_state = _lazy_import_docker()
            ui_data = get_ui_state()
            ui_data["response"] = command_output
            return ui_data
        except Exception as e:
            try:
                # Try to get UI state even on error
                _, _, get_ui_state = _lazy_import_docker()
                ui_data = get_ui_state()
            except:
                ui_data = {"ui_elements": []}
            ui_data["response"] = f"Error: {str(e)}"
            return ui_data


if __name__ == "__main__":
    logger.info("Starting MCP server in stdio mode for Claude Desktop")
    mcp.run(transport="stdio")
