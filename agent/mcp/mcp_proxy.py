#!/usr/bin/env python3
"""
MCP Proxy for Codex CLI Integration

This script acts as a bridge between Codex CLI (which expects stdio MCP protocol)
and our HTTP-based MCP server running on localhost:8000.
"""

import json
import sys
from typing import Any, Dict

import requests


class MCPProxy:
    def __init__(self, mcp_server_url: str = "http://localhost:8000/mcp"):
        self.mcp_server_url = mcp_server_url
        self.session = requests.Session()

    def send_request(
        self, method: str, params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Send request to HTTP MCP server and return response."""
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}

        try:
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
                            return json.loads(data_json)
                        except json.JSONDecodeError:
                            continue
                # Fallback if no valid JSON found
                return {
                    "error": {
                        "code": -32603,
                        "message": "Failed to parse event-stream response",
                    }
                }
            else:
                return response.json()
        except requests.RequestException as e:
            return {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32603, "message": f"HTTP request failed: {str(e)}"},
            }

    def handle_stdio(self):
        """Handle stdio MCP protocol communication."""
        # Process stdin for MCP protocol messages
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
                method = request.get("method")
                params = request.get("params", {})
                request_id = request.get("id")

                # Handle notifications (no id field, no response required)
                if request_id is None:
                    # Notifications like notifications/initialized don't need a response
                    continue

                if method == "initialize":
                    # Respond with server capabilities
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {
                                "name": "MobileCyberBench MCP Proxy",
                                "version": "1.0.0",
                            },
                        },
                    }

                elif method == "tools/list":
                    # Return available tools
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "tools": [
                                {
                                    "name": "execute_command",
                                    "description": "Execute a terminal command for Android testing",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "command": {
                                                "type": "string",
                                                "description": "The command to execute",
                                            }
                                        },
                                        "required": ["command"],
                                    },
                                }
                            ]
                        },
                    }

                elif method == "tools/call":
                    # Forward tool call to HTTP MCP server
                    tool_name = params.get("name")
                    tool_args = params.get("arguments", {})

                    if tool_name == "execute_command":
                        command = tool_args.get("command", "")
                        # Make HTTP request to actual MCP server
                        http_response = self.send_request(
                            "tools/call",
                            {
                                "name": "execute_command",
                                "arguments": {"command": command},
                            },
                        )

                        # Extract the actual command output from MCP server response
                        if "result" in http_response:
                            result = http_response["result"]

                            # Check for content array (standard MCP format)
                            if "content" in result and isinstance(
                                result["content"], list
                            ):
                                if len(result["content"]) > 0:
                                    # Get text from first content item
                                    first_content = result["content"][0]
                                    if isinstance(first_content, dict):
                                        actual_output = first_content.get(
                                            "text", "Command executed"
                                        )
                                    else:
                                        actual_output = str(first_content)
                                else:
                                    actual_output = "Command executed (empty content)"

                            # Fallback: check for structuredContent (custom format)
                            elif "structuredContent" in result:
                                if isinstance(result["structuredContent"], dict):
                                    actual_output = result["structuredContent"].get(
                                        "result", "Command executed"
                                    )
                                else:
                                    actual_output = str(result["structuredContent"])

                            # Fallback: check for direct result field
                            elif "result" in result:
                                actual_output = str(result["result"])

                            else:
                                # Debug: log what we actually got
                                actual_output = (
                                    f"Unexpected response format: {json.dumps(result)}"
                                )

                        elif "error" in http_response:
                            # Handle error response
                            error = http_response["error"]
                            actual_output = (
                                f"Error: {error.get('message', 'Unknown error')}"
                            )
                        else:
                            actual_output = "Command executed (no result)"

                        # Forward response
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "content": [{"type": "text", "text": actual_output}]
                            },
                        }
                    else:
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {
                                "code": -32601,
                                "message": f"Unknown tool: {tool_name}",
                            },
                        }

                else:
                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32601,
                            "message": f"Unknown method: {method}",
                        },
                    }

                # Send response back to Codex CLI
                print(json.dumps(response))
                sys.stdout.flush()

            except json.JSONDecodeError:
                continue
            except Exception as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": request.get("id", 1) if "request" in locals() else 1,
                    "error": {"code": -32603, "message": f"Internal error: {str(e)}"},
                }
                print(json.dumps(error_response))
                sys.stdout.flush()


def main():
    """Main entry point for MCP proxy."""
    import os

    # Get MCP server URL from environment or use default
    mcp_url = os.getenv("MCP_SERVER_URL", "http://localhost:8000/mcp")

    proxy = MCPProxy(mcp_url)
    proxy.handle_stdio()


if __name__ == "__main__":
    main()
