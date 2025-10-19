import os
import shlex
from functools import lru_cache

from docker_setup import HOST_ADB_SERVER, get_kali
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from ui_connection import EmulatorState, get_ui_state

from tools.token_truncator import TokenTruncator
from utils.logger import logger

mcp = FastMCP(name="Mobile Cyber MCP", stateless_http=True)


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


@mcp.tool(
    description="Execute a terminal command. For adb commands, write 'adb shell ...'. "
)
def execute_command(command: str) -> EmulatorState:
    """
    The main tool for the AI model to be able to interact with our Kali container.
    """
    try:
        container = get_kali()
        start_dir = os.getenv("START_DIR", "/app/codebase")

        # Determine if the command is an ADB command
        if command.strip().startswith("adb"):
            # Prefix ADB server socket export and change to start directory
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

        truncated_response = header + truncated_body

        # Returns the emulator state
        return get_ui_state(truncated_response)

    except Exception as e:
        return get_ui_state(f"Error: {str(e)}")


if __name__ == "__main__":
    mcp.run(transport="http", port=8000)
