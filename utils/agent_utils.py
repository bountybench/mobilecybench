import base64
import io
import os
from datetime import datetime

import docker
from PIL import Image as PILImage

from utils.logger import logger

DOCKER_CLIENT = docker.from_env()
KALI_CONTAINER_NAME = "kali-container"  # from agent/docker-compose.yml
HOST_ADB_SERVER = "host.docker.internal:5037"  # from agent/docker-compose.yml


def encode_image(image_data: bytes) -> str:
    """Encode image data as base64 string"""
    return base64.b64encode(image_data).decode("utf-8")


def take_screenshot(
    compress_level: int = 6, max_width: int = 300, save_to_file: bool = True
):
    """
    Takes a compressed screenshot of the emulator and returns it as base64 encoded image data.

    Args:
        compress_level (int): PNG compression level (0-9, default 6)
        max_width (int): Maximum width for resizing (default 300)
        save_to_file (bool): Whether to save screenshot to file (default True)

    Returns:
        dict: Contains success status, base64 encoded image data, and metadata
    """
    logger.info("SCREENSHOT: Starting capture...")

    try:
        kali_container = DOCKER_CLIENT.containers.get(KALI_CONTAINER_NAME)
        cmd = f"export ADB_SERVER_SOCKET=tcp:{HOST_ADB_SERVER} && adb exec-out screencap -p"
        result = kali_container.exec_run(f"bash -c '{cmd}'", stdout=True, stderr=True)

        if result.exit_code != 0:
            error_msg = result.output.decode("utf-8")
            logger.error(f"ERROR: Screenshot failed: {error_msg}")
            return {
                "success": False,
                "error": f"Error taking screenshot: {error_msg}",
                "image_data": None,
            }

        # Process and compress image
        image = PILImage.open(io.BytesIO(result.output))

        # Resize if too wide
        if image.width > max_width:
            ratio = max_width / image.width
            new_height = int(image.height * ratio)
            image = image.resize((max_width, new_height), PILImage.Resampling.LANCZOS)

        # Compress and encode as PNG
        output_buffer = io.BytesIO()
        image.save(
            output_buffer, format="PNG", optimize=True, compress_level=compress_level
        )
        image_bytes = output_buffer.getvalue()
        image_base64 = encode_image(image_bytes)

        result_data = {
            "success": True,
            "image_data": image_base64,
            "format": "png",
            "size_bytes": len(image_bytes),
            "dimensions": (image.width, image.height),
            "compress_level": compress_level,
        }

        # Save to file if requested
        if save_to_file:
            screenshots_dir = "./screenshots"
            os.makedirs(screenshots_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_filename = f"screenshot_{timestamp}.png"
            screenshot_path = os.path.join(screenshots_dir, screenshot_filename)

            # Save the compressed image to file
            with open(screenshot_path, "wb") as f:
                f.write(image_bytes)

            logger.info(f"Screenshot saved to {screenshot_path}")
            result_data["file_path"] = screenshot_path

        logger.info(f"✓ Screenshot success; response size: {len(image_bytes)} bytes")
        return result_data

    except Exception as e:
        logger.error(f"ERROR: Screenshot exception: {str(e)}")
        return {"success": False, "error": str(e), "image_data": None}
