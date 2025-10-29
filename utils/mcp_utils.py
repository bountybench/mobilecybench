import json
import logging
import subprocess
from typing import Optional

import requests


def discover_ngrok_base_url(logger: Optional[logging.Logger] = None) -> str:
    """
    Discover the ngrok base URL (without any endpoints) by querying the ngrok API.

    Returns:
        The base ngrok URL (e.g., "https://abc123.ngrok.io")
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    try:
        logger.info("Attempting to discover ngrok base URL...")
        result = subprocess.run(
            [
                "docker",
                "exec",
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
            ngrok_base_url = tunnels_data["tunnels"][0]["public_url"]
            logger.info(f"Discovered ngrok base URL: {ngrok_base_url}")
            return ngrok_base_url
        else:
            raise RuntimeError("No ngrok tunnels found")

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to execute docker command: {e}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse ngrok response: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error during ngrok base URL discovery: {e}")


def check_server_health(server_url: str, timeout: int = 10) -> bool:
    """
    Check if the server is reachable by using its health endpoint.
    Accepts URLs with or without the /mcp endpoint.

    Args:
        server_url: The server URL to check (e.g., "https://abc123.ngrok.io" or "https://abc123.ngrok.io/mcp/")
        timeout: Request timeout in seconds

    Returns:
        True if server is reachable and healthy, False otherwise
    """
    try:
        # Strip /mcp/ endpoint if present to get the base URL for health check
        base_url = server_url.rstrip("/")
        if base_url.endswith("/mcp"):
            base_url = base_url[:-4]  # Remove "/mcp" from the end

        # Use base URL server's health check endpoint
        health_url = base_url + "/health"
        response = requests.get(health_url, timeout=timeout)
        return response.status_code == 200 and response.text.strip() == "OK"
    except requests.exceptions.RequestException:
        return False


def get_mcp_server_config(
    ngrok_base_url: str = None,
    allowed_tools: list = None,
    check_reachability: bool = True,
    experiment_id: str = None,
) -> dict:
    """
    Get MCP server configuration by constructing the MCP endpoint URL from the ngrok base URL.

    Args:
        ngrok_base_url: The ngrok base URL (e.g., "https://abc123.ngrok.io").
                       If None, will auto-discover from ngrok API.
        allowed_tools: List of allowed tools for the MCP server
        check_reachability: Whether to check if the server is reachable before returning config

    Returns:
        Dictionary containing MCP server configuration
    """
    if ngrok_base_url is None:
        ngrok_base_url = discover_ngrok_base_url()

    # Construct the MCP server URL with experiment_id for routing
    base_url = ngrok_base_url.rstrip("/")
    if experiment_id:
        mcp_server_url = f"{base_url}/mcp/{experiment_id}/"
    else:
        mcp_server_url = f"{base_url}/mcp/"

    # Check if server is reachable before returning config
    if check_reachability and not check_server_health(mcp_server_url):
        raise RuntimeError(
            f"MCP server at {mcp_server_url} is not reachable (base URL: {ngrok_base_url})"
        )

    config = {
        "type": "mcp",
        "server_label": "mobile_server_mcp",
        "server_url": mcp_server_url,
        "require_approval": "never",
    }

    # Add allowed_tools if specified
    if allowed_tools is not None:
        config["allowed_tools"] = allowed_tools

    return config
