"""
LangGraph native tools for executing commands in Kali container and interacting with Android emulator.

This module provides tools that:
1. Execute commands in the Kali container via docker exec
2. Run ADB commands to interact with Android emulator
3. Get emulator information and status

All tools are designed to work with LangGraph's tool system using the @tool decorator.
"""

import json
import shlex
import sys
from pathlib import Path

from langchain_core.tools import tool

from utils.logger import agent_logger

# Add agent/mcp to path to allow command_helpers imports
mcp_path = Path(__file__).parent.parent / "mcp"
if str(mcp_path) not in sys.path:
    sys.path.insert(0, str(mcp_path))

# Now import from MCP modules
from command_helpers import (  # noqa: E402
    execute_adb_command_with_retry,
    is_adb_command_allowed,
)
from docker_setup import get_kali  # noqa: E402


@tool
def execute_command(command: str) -> str:
    """
    Execute a command in the Kali container and return the output.

    This tool runs any shell command inside the Kali Linux container.
    Commands are executed in the /app/codebase directory by default.

    Args:
        command: The shell command to execute (e.g., "ls -la", "whoami", "cat file.txt")

    Returns:
        String containing command output, exit code, and any errors

    Example:
        >>> execute_command("whoami")
        "Command: whoami\\nExit Code: 0\\nOutput:\\nroot"

        >>> execute_command("ls /app/codebase")
        "Command: ls /app/codebase\\nExit Code: 0\\nOutput:\\nfile1.txt\\nfile2.py"
    """
    try:
        agent_logger.info(f"Executing command in Kali: {command}")

        container = get_kali()
        start_dir = "/app/codebase"

        # Build full command
        full_cmd = f"cd {start_dir} && {command}"

        # Execute in container
        result = container.exec_run(
            f"bash -c {shlex.quote(full_cmd)}", stdout=True, stderr=True
        )

        exit_code = result.exit_code
        output = result.output.decode("utf-8", errors="replace")

        # Format response
        response = f"Command: {command}\nExit Code: {exit_code}\nOutput:\n{output}"

        agent_logger.info(
            f"Command completed with exit code {exit_code}, output length: {len(output)}"
        )

        return response

    except Exception as e:
        error_msg = f"Error executing command '{command}': {str(e)}"
        agent_logger.error(error_msg)
        return f"Error: {error_msg}"


@tool
def execute_adb_command(command: str) -> str:
    """
    Execute an ADB command to interact with the Android emulator.

    This tool runs ADB (Android Debug Bridge) commands to control and inspect
    the Android emulator. The ADB server connection is automatically configured
    to connect from Kali to the host's ADB server at host.docker.internal:5037.

    Safety: Blocked ADB patterns (e.g., dangerous operations) are filtered.
    The command will automatically retry on connection errors.

    Args:
        command: The ADB command to execute (e.g., "adb devices", "adb shell getprop")

    Returns:
        String containing command output, exit code, and any errors

    Example:
        >>> execute_adb_command("adb devices")
        "Command: adb devices\\nExit Code: 0\\nOutput:\\nList of devices attached\\nemulator-5554\\tdevice"

        >>> execute_adb_command("adb shell getprop ro.build.version.release")
        "Command: adb shell getprop ro.build.version.release\\nExit Code: 0\\nOutput:\\n13"
    """
    try:
        agent_logger.info(f"Executing ADB command: {command}")

        # Check if command is allowed
        if not is_adb_command_allowed(command):
            error_msg = f"ADB command blocked for safety: {command}"
            agent_logger.warning(error_msg)
            return f"Error: {error_msg}"

        # Execute with retry logic
        start_dir = "/app/codebase"
        exit_code, output = execute_adb_command_with_retry(
            command=command, start_dir=start_dir, max_retries=2
        )

        # Format response
        response = f"Command: {command}\nExit Code: {exit_code}\nOutput:\n{output}"

        agent_logger.info(
            f"ADB command completed with exit code {exit_code}, output length: {len(output)}"
        )

        return response

    except Exception as e:
        error_msg = f"Error executing ADB command '{command}': {str(e)}"
        agent_logger.error(error_msg)

        # Provide helpful error message for connection issues
        if "no devices/emulators found" in str(e).lower():
            error_msg += "\n\nTip: The emulator may not be running or ADB connection is not established. Try starting the emulator first."

        return f"Error: {error_msg}"


@tool
def get_emulator_info() -> str:
    """
    Get current Android emulator status and device information.

    This tool retrieves comprehensive information about the connected Android emulator,
    including device list, Android version, device properties, and connectivity status.

    Returns:
        JSON string containing emulator information with fields:
        - devices: List of connected devices
        - android_version: Android OS version
        - device_model: Device model name
        - status: Connection status
        - error: Error message if any

    Example:
        >>> get_emulator_info()
        '{
            "devices": "emulator-5554\\tdevice",
            "android_version": "13",
            "device_model": "sdk_gphone64_arm64",
            "sdk_version": "33",
            "status": "connected"
        }'
    """
    try:
        agent_logger.info("Getting emulator information")

        info = {}

        # Get device list
        devices_exit, devices_output = execute_adb_command_with_retry(
            "adb devices", "/app/codebase"
        )
        info["devices"] = devices_output.strip()

        # If devices are connected, get more info
        if devices_exit == 0 and "device" in devices_output:
            # Get Android version
            version_exit, version_output = execute_adb_command_with_retry(
                "adb shell getprop ro.build.version.release", "/app/codebase"
            )
            if version_exit == 0:
                info["android_version"] = version_output.strip()

            # Get device model
            model_exit, model_output = execute_adb_command_with_retry(
                "adb shell getprop ro.product.model", "/app/codebase"
            )
            if model_exit == 0:
                info["device_model"] = model_output.strip()

            # Get SDK version
            sdk_exit, sdk_output = execute_adb_command_with_retry(
                "adb shell getprop ro.build.version.sdk", "/app/codebase"
            )
            if sdk_exit == 0:
                info["sdk_version"] = sdk_output.strip()

            info["status"] = "connected"
        else:
            info["status"] = "no_device"
            info[
                "error"
            ] = "No emulator devices found. Please start the Android emulator."

        result = json.dumps(info, indent=2)
        agent_logger.info(f"Emulator info retrieved: {info.get('status')}")

        return result

    except Exception as e:
        error_msg = f"Error getting emulator info: {str(e)}"
        agent_logger.error(error_msg)
        return json.dumps({"status": "error", "error": error_msg}, indent=2)


@tool
def get_ui_state() -> str:
    """
    Get current Android UI state with all interactive elements.

    Returns structured JSON with UI element hierarchy from uiautomator dump.
    Use this by default for UI inspection - it's fast and token-efficient.

    Returns:
        JSON string with ui_elements array containing clickable/scrollable elements,
        text, resource IDs, bounds, and locations.

    Example output:
        {
            "ui_elements": [
                {
                    "text": "Login",
                    "resource_id": "com.example:id/login_btn",
                    "class_name": "android.widget.Button",
                    "clickable": true,
                    "location": [540, 1200]
                }
            ]
        }
    """
    try:
        agent_logger.info("Getting UI state")
        from ui_connection import get_ui_state as _get_ui_state

        ui_data = _get_ui_state()
        result = json.dumps(ui_data, indent=2)

        element_count = len(ui_data.get("ui_elements", []))
        agent_logger.info(f"UI state retrieved: {element_count} elements")

        return result

    except Exception as e:
        error_msg = f"Error getting UI state: {str(e)}"
        agent_logger.error(error_msg)
        return json.dumps({"ui_elements": [], "error": error_msg}, indent=2)


@tool
def take_screenshot() -> str:
    """
    Capture screenshot of Android emulator screen.

    Returns base64-encoded PNG image for visual analysis.
    WARNING: High token cost - only use when visual context is critical.
    Prefer get_ui_state() for routine UI inspection.

    Use when you need to:
    - Verify visual changes from exploits
    - Detect permission dialogs, crashes
    - Analyze complex visual layouts

    Returns:
        JSON string with success status and base64 image data
    """
    try:
        agent_logger.info("Taking screenshot")
        from utils.agent_utils import take_screenshot as _take_screenshot

        result = _take_screenshot(compress_level=6, max_width=400, save_to_file=True)

        if result.get("success"):
            agent_logger.info("Screenshot captured successfully")
            return json.dumps(
                {
                    "success": True,
                    "image_data": result["image_data"],
                    "width": result.get("width"),
                    "height": result.get("height"),
                }
            )
        else:
            return json.dumps({"success": False, "error": result.get("error")})

    except Exception as e:
        error_msg = f"Error taking screenshot: {str(e)}"
        agent_logger.error(error_msg)
        return json.dumps({"success": False, "error": error_msg})


KALI_TOOLS = [
    execute_command,
    execute_adb_command,
    get_emulator_info,
    get_ui_state,
    take_screenshot,
]
