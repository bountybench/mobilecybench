import os
import shlex

from docker_setup import HOST_ADB_SERVER, get_kali
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from ui_connection import EmulatorState, get_ui_state

mcp = FastMCP(name="Mobile Cyber MCP", stateless_http=True)


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    """Health check endpoint for container orchestration"""
    return PlainTextResponse("OK")


@mcp.tool(
    description="Execute a terminal command. For adb commands, write 'adb shell ...'. "
)
def execute_command(command: str) -> EmulatorState:
    """
    The main tool for the AI model to be able to interact with our
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
        output = result.output.decode("utf-8")

        # Returns the emulator state
        return get_ui_state(
            f"{label}: {command}\nExit Code: {result.exit_code}\nOutput:\n{output}"
        )

    except Exception as e:
        return get_ui_state(f"Error: {str(e)}")


if __name__ == "__main__":
    mcp.run(transport="http", port=8000, host="0.0.0.0")
