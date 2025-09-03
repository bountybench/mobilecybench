import logging
import base64
import io
import os
import shlex
from datetime import datetime
from PIL import Image

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


@mcp.tool(
    description="Takes a compressed screenshot of the emulator and returns it as structured image data for vision models."
)
def take_screenshot(quality: int = 40, max_width: int = 300) -> dict:
    """Takes a compressed screenshot of the emulator and returns it as structured image data for vision models."""
    logger.info("📸 SCREENSHOT: Starting capture...")

    try:
        container = get_kali()
        cmd = f"export ADB_SERVER_SOCKET=tcp:{HOST_ADB_SERVER} && adb exec-out screencap -p"
        result = container.exec_run(f"bash -c '{cmd}'", stdout=True, stderr=True)

        if result.exit_code != 0:
            error_msg = result.output.decode("utf-8")
            logger.error(f"❌ SCREENSHOT: Error - {error_msg}")
            return {
                "type": "error",
                "content": f"Error taking screenshot: {error_msg}"
            }

        # Process and compress image
        image = Image.open(io.BytesIO(result.output))

        # Resize if too wide
        if image.width > max_width:
            ratio = max_width / image.width
            new_height = int(image.height * ratio)
            image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)

        # Convert to RGB for JPEG compression
        if image.mode != "RGB":
            if image.mode in ("RGBA", "LA", "P"):
                # Handle transparency with white background
                background = Image.new("RGB", image.size, (255, 255, 255))
                if image.mode == "P":
                    image = image.convert("RGBA")
                background.paste(
                    image, mask=image.split()[-1] if image.mode == "RGBA" else None
                )
                image = background
            else:
                image = image.convert("RGB")

        # Compress and encode
        output_buffer = io.BytesIO()
        image.save(output_buffer, format="JPEG", quality=quality, optimize=True)
        base64_data = base64.b64encode(output_buffer.getvalue()).decode("utf-8")

        # Save screenshot to local file for verification
        # This path is mounted as a volume in the Docker container
        screenshots_dir = "/screenshots"
        os.makedirs(screenshots_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        screenshot_filename = f"screenshot_{timestamp}.jpg"
        screenshot_path = os.path.join(screenshots_dir, screenshot_filename)
        
        # Save the compressed image to file
        with open(screenshot_path, "wb") as f:
            f.write(output_buffer.getvalue())
        
        logger.info(f"💾 SCREENSHOT: Saved to {screenshot_path}")

        response = {
                        "type": "image",
                        "data": f"data:image/jpeg;base64,{base64_data}",
                        "mimeType": "image/jpeg",
                    }
        
        logger.info(f"✅ SCREENSHOT: Success! Response size: {len(base64_data)} chars")
        return response

    except Exception as e:
        logger.error(f"❌ SCREENSHOT: Exception - {str(e)}")
        return {
            "type": "error",
            "content": f"Error: {str(e)}"
        }


if __name__ == "__main__":
    mcp.run(transport="http", port=8000)
