import base64
import io
from datetime import datetime
from functools import lru_cache

import docker
from PIL import Image as PILImage

from utils.logger import logger

KALI_CONTAINER_NAME = "kali-container"  # from agent/docker-compose.yml
HOST_ADB_SERVER = "host.docker.internal:5037"  # from agent/docker-compose.yml


@lru_cache(maxsize=1)
def get_docker_client():
    return docker.from_env()


def encode_image(image_data: bytes) -> str:
    """Encode image data as base64 string"""
    return base64.b64encode(image_data).decode("utf-8")


def take_screenshot(compress_level: int = 6, max_width: int = 300):
    """
    Takes a compressed screenshot of the emulator and returns it as base64 encoded image data.

    Args:
        compress_level (int): PNG compression level (0-9, default 6)
        max_width (int): Maximum width for resizing (default 300)

    Returns:
        dict: Contains success status, base64 encoded image data, and metadata
    """
    from utils.logger import logger_manager

    logger.info("Capturing compressed screenshot...")

    try:
        kali_container = get_docker_client().containers.get(KALI_CONTAINER_NAME)
        cmd = f"export ADB_SERVER_SOCKET=tcp:{HOST_ADB_SERVER} && adb exec-out screencap -p"
        result = kali_container.exec_run(f"bash -c '{cmd}'", stdout=True, stderr=True)

        if result.exit_code != 0:
            error_msg = result.output.decode("utf-8")
            logger.error(f"Screenshot failed: {error_msg}")
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

        # Save to experiment logs directory if active
        logs_dir = logger_manager.get_logs_dir()
        if logs_dir:
            screenshots_dir = logs_dir / "screenshots"
            screenshots_dir.mkdir(exist_ok=True, parents=True)

            # Use timestamp for uniqueness within the turn
            timestamp = datetime.now().strftime("%H%M%S_%f")
            screenshot_filename = f"capture_{timestamp}.png"
            screenshot_path = screenshots_dir / screenshot_filename

            with open(screenshot_path, "wb") as f:
                f.write(image_bytes)

            result_data["file_path"] = str(screenshot_path)

        logger.info(f"✓ Screenshot success; {len(image_bytes)} bytes")
        return result_data

    except Exception as e:
        logger.error(f"Screenshot exception: {str(e)}")
        return {"success": False, "error": str(e), "image_data": None}
