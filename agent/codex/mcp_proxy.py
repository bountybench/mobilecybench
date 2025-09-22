#!/usr/bin/env python3
"""
MCP Proxy for Containerized Codex Agent

This script acts as a bridge between Codex CLI (which expects stdio MCP protocol)
and the Kali security container's HTTP-based MCP server running on kali-security:8000.

This is specifically designed for the containerized architecture where:
- Codex CLI runs in codex-agent container
- MCP server runs in kali-security container
- Communication happens via Docker networking
"""

import json
import logging
import os
import sys
from typing import Any, Dict

import requests

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ContainerMCPProxy:
    def __init__(self, mcp_server_url: str = None):
        self.mcp_server_url = mcp_server_url or os.getenv(
            "MCP_SERVER_URL", "http://kali-security:8000/mcp"
        )
        self.session = requests.Session()

        # Set reasonable timeouts for container networking
        self.session.timeout = 30

        logger.info(f"MCP Proxy initialized for {self.mcp_server_url}")

    def send_request(
        self, method: str, params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Send request to Kali container's HTTP MCP server and return response."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}

        try:
            logger.debug(f"Sending MCP request: {method}")

            response = self.session.post(
                self.mcp_server_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                timeout=30,
            )
            response.raise_for_status()

            # Handle event-stream response format from FastMCP
            if "text/event-stream" in response.headers.get("content-type", ""):
                # Parse event-stream format
                lines = response.text.strip().split("\n")
                for line in lines:
                    if line.startswith("data: "):
                        data_json = line[6:]  # Remove 'data: ' prefix
                        try:
                            result = json.loads(data_json)
                            logger.debug(f"MCP response received: {method}")
                            return result
                        except json.JSONDecodeError:
                            continue
                # Fallback if no valid JSON found
                return {"error": "No valid JSON in event stream"}
            else:
                # Handle regular JSON response
                result = response.json()
                logger.debug(f"MCP response received: {method}")
                return result

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            return {
                "error": f"Cannot connect to Kali security container at {self.mcp_server_url}. "
                f"Ensure kali-security container is running and accessible."
            }
        except requests.exceptions.Timeout as e:
            logger.error(f"MCP request timed out: {e}")
            return {"error": "MCP request timed out"}
        except Exception as e:
            logger.error(f"MCP request failed: {e}")
            return {"error": f"MCP request failed: {str(e)}"}

    def handle_stdio_protocol(self):
        """Handle stdio MCP protocol that Codex CLI expects."""
        logger.info("Starting MCP proxy stdio handler")

        try:
            for line in sys.stdin:
                try:
                    request = json.loads(line.strip())
                    method = request.get("method")
                    params = request.get("params", {})

                    # Forward request to Kali container
                    response = self.send_request(method, params)

                    # Send response back via stdout
                    json.dump(response, sys.stdout)
                    sys.stdout.write("\n")
                    sys.stdout.flush()

                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON in request: {e}")
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id", 1) if "request" in locals() else 1,
                        "error": {"code": -32700, "message": "Parse error"},
                    }
                    json.dump(error_response, sys.stdout)
                    sys.stdout.write("\n")
                    sys.stdout.flush()

        except KeyboardInterrupt:
            logger.info("MCP proxy terminated by user")
        except Exception as e:
            logger.error(f"MCP proxy error: {e}")
            sys.exit(1)


def main():
    """Main entry point for MCP proxy."""
    proxy = ContainerMCPProxy()

    # Test connection to Kali container on startup
    try:
        test_response = proxy.send_request("initialize")
        if "error" in test_response:
            logger.warning(
                f"MCP server connection test failed: {test_response['error']}"
            )
        else:
            logger.info("Successfully connected to Kali security container MCP server")
    except Exception as e:
        logger.warning(f"Could not test MCP connection: {e}")

    # Start handling stdio protocol
    proxy.handle_stdio_protocol()


if __name__ == "__main__":
    main()
