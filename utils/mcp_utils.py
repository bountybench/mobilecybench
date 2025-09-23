import json
import logging
import subprocess
from typing import Optional

import requests


def discover_mcp_server_url(logger: Optional[logging.Logger] = None) -> str:
    if logger is None:
        logger = logging.getLogger(__name__)

    try:
        logger.info("Attempting to discover MCP server URL via ngrok...")
        result = subprocess.run(
            [
                "docker",
                "exec",
                "-it",
                "mcp-server",
                "curl",
                "http://localhost:4040/api/tunnels",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        logger.debug(f"Raw ngrok response: {result.stdout}")
        tunnels_data = json.loads(result.stdout)

        if tunnels_data.get("tunnels") and len(tunnels_data["tunnels"]) > 0:
            public_url = tunnels_data["tunnels"][0]["public_url"]
            logger.info(f"Discovered MCP server URL: {public_url}")
            return public_url
        else:
            raise RuntimeError("No ngrok tunnels found")

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to execute docker command: {e}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse ngrok response: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error during MCP server discovery: {e}")


def check_mcp_server_reachable(server_url: str, timeout: int = 10) -> bool:
    """
    Check if the MCP server is reachable by making a simple HTTP request.

    Args:
        server_url: The MCP server URL to check
        timeout: Request timeout in seconds

    Returns:
        True if server is reachable, False otherwise
    """
    try:
        # Try a simple GET request to check if server is up
        response = requests.get(server_url, timeout=timeout)
        return response.status_code < 500  # Accept any non-server-error response
    except requests.exceptions.RequestException:
        return False


def get_mcp_server_config(
    server_url: str = None, allowed_tools: list = None, check_reachability: bool = True
) -> dict:
    if server_url is None:
        server_url = discover_mcp_server_url()

    # Ensure URL has the /mcp/ endpoint with trailing slash
    if not server_url.endswith("/mcp/"):
        server_url = server_url.rstrip("/") + "/mcp/"

    # Check if server is reachable before returning config
    if check_reachability and not check_mcp_server_reachable(server_url):
        raise RuntimeError(f"MCP server at {server_url} is not reachable")

    config = {
        "type": "mcp",
        "server_label": "mobile_server_mcp",
        "server_url": server_url,
        "require_approval": "never",
    }

    # Add allowed_tools if specified
    if allowed_tools is not None:
        config["allowed_tools"] = allowed_tools

    return config
