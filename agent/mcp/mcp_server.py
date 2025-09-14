import logging
import os
import shlex

from docker_setup import HOST_ADB_SERVER, get_kali
from fastmcp import FastMCP
from ui_connection import EmulatorState, get_ui_state

# Simple logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

mcp = FastMCP(name="Mobile Cyber MCP", stateless_http=True)


@mcp.tool(
    description="Execute a terminal command. For adb commands, write 'adb shell ...'. "
)
def execute_command(command: str) -> EmulatorState:
    """
    The main tool for the AI model to be able to interact with our
    """
    try:
        container = get_kali()

        # Get the starting directory from environment variable, default to /root
        start_dir = os.getenv("START_DIR", "/root")

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


# @mcp.tool(
#     description="Takes a compressed screenshot of the emulator and returns it as structured image data."
# )
# def take_screenshot(compress_level: int = 6, max_width: int = 300) -> FastMCPImage:
#     """Takes a compressed screenshot of the emulator and returns it as structured image data."""
#     logger.info("📸 SCREENSHOT: Starting capture...")

#     try:
#         container = get_kali()
#         cmd = f"export ADB_SERVER_SOCKET=tcp:{HOST_ADB_SERVER} && adb exec-out screencap -p"
#         result = container.exec_run(f"bash -c '{cmd}'", stdout=True, stderr=True)

#         if result.exit_code != 0:
#             error_msg = result.output.decode("utf-8")
#             logger.error(f"❌ SCREENSHOT: Error - {error_msg}")
#             return {"type": "error", "content": f"Error taking screenshot: {error_msg}"}

#         # Process and compress image
#         image = PILImage.open(io.BytesIO(result.output))

#         # Resize if too wide
#         if image.width > max_width:
#             ratio = max_width / image.width
#             new_height = int(image.height * ratio)
#             image = image.resize((max_width, new_height), PILImage.Resampling.LANCZOS)

#         # Compress and encode as PNG (no RGB conversion needed)
#         output_buffer = io.BytesIO()
#         image.save(
#             output_buffer, format="PNG", optimize=True, compress_level=compress_level
#         )
#         image_bytes = output_buffer.getvalue()

#         # This path is mounted as a volume in the Docker container
#         # And also saves the screenshot to the local host for viewing
#         screenshots_dir = "/screenshots"
#         os.makedirs(screenshots_dir, exist_ok=True)

#         timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
#         screenshot_filename = f"screenshot_{timestamp}.png"
#         screenshot_path = os.path.join(screenshots_dir, screenshot_filename)

#         # Save the compressed image to file
#         with open(screenshot_path, "wb") as f:
#             f.write(image_bytes)

#         logger.info(f"💾 SCREENSHOT: Saved to {screenshot_path}")

#         logger.info(f"✅ SCREENSHOT: Success! Response size: {len(image_bytes)} bytes")
#         fastmcp_image = FastMCPImage(data=image_bytes, format="png")
#         return fastmcp_image

#     except Exception as e:
#         logger.error(f"❌ SCREENSHOT: Exception - {str(e)}")
#         raise


if __name__ == "__main__":
    mcp.run(transport="http", port=8000)
