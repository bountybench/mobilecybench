#!/usr/bin/env python3
"""
MCP Tools Checker

This helper script discovers the running MCP server and exercises its tools
over HTTP. It is intended for quick, manual validation that the MCP server is
reachable and that specific tools (e.g., take_screenshot, execute_command) are
working end-to-end.

Usage
-----
Run from the repository root or from the `agent/` directory.

Basic commands:
  - List tools:
      python3 agent/test_mcp_tools.py list
  - Test a specific tool (examples):
      python3 agent/test_mcp_tools.py test take_screenshot
      python3 agent/test_mcp_tools.py test execute_command "ls -la"
  - Show the MCP server public URL (via ngrok):
      python3 agent/test_mcp_tools.py url

Prerequisites
-------------
  - MCP server is running (e.g., via: docker compose up -d in `agent/`).
  - `agent/mcp/ngrok.yml` exists and is configured.
  - Network access to the MCP server (local Docker network or ngrok tunnel).
  - Python dependencies installed (see project requirements) including `requests`.

"""

import json
import os
import sys
from typing import Any, Dict, Optional

import requests

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from utils.logger import logger
from utils.mcp_utils import discover_mcp_server_url, get_mcp_server_config


def call_mcp_server(
    method: str, params: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """Call MCP server over HTTP using utils configuration.

    Tries JSON response first; also supports SSE-style 'data: ' lines.
    """
    try:
        config = get_mcp_server_config(check_reachability=False)
        mcp_server_url = config["server_url"]  # guaranteed to end with /mcp/

        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        resp = requests.post(
            mcp_server_url, headers=headers, data=json.dumps(payload), timeout=20
        )
        resp.raise_for_status()

        # Try plain JSON first
        try:
            return resp.json()
        except ValueError:
            pass  # Pass and attempt to parse SSE format

        # Parse SSE format (look for lines starting with "data: ")
        lines = resp.text.splitlines()
        for line in lines:
            if line.startswith("data: "):
                data_str = line[6:].strip()
                try:
                    return json.loads(data_str)
                except Exception:
                    continue
        return None
    except requests.RequestException as e:
        logger.error("HTTP error calling MCP server: %s", e)
        return None
    except Exception as e:
        logger.error("Unexpected error calling MCP server: %s", e)
        return None


def list_tools():
    """List available MCP tools"""
    print("List MCP Server Tools")
    print("=" * 60)

    result = call_mcp_server("tools/list")
    if result and "result" in result and "tools" in result["result"]:
        tools = result["result"]["tools"]
        print(f"✓ Found {len(tools)} tools:\n")

        for i, tool in enumerate(tools, 1):
            print(f"{i}. {tool['name']}")
            print(f"   {tool['description']}")

            # Show parameters
            if "inputSchema" in tool and "properties" in tool["inputSchema"]:
                params = list(tool["inputSchema"]["properties"].keys())
                if params:
                    print(f"   Parameters: {', '.join(params)}")
            print()

        return tools
    else:
        print("✕ No tools found or server not responding")
        return None


def test_tool(tool_name, arguments):
    """Test a specific tool"""
    print(f"Testing {tool_name}")
    print("=" * 60)

    result = call_mcp_server("tools/call", {"name": tool_name, "arguments": arguments})

    if result and "result" in result:
        print("✓ Success!")
        print(f"Result: {result['result']}")
    elif result and "error" in result:
        print(f"✕ Error: {result['error']}")
    else:
        print("✕ No response from server")


def main():
    if len(sys.argv) == 1:
        # List tools
        tools = list_tools()
        if tools:
            print("Usage:")
            print("  python3 test_mcp_tools.py list                    # List tools")
            print("  python3 test_mcp_tools.py test <tool> <args>      # Test tool")
            print(
                "  python3 test_mcp_tools.py url                     # Show ngrok URL"
            )

    elif sys.argv[1] == "list":
        list_tools()

    elif sys.argv[1] == "test" and len(sys.argv) >= 3:
        tool_name = sys.argv[2]
        if tool_name == "execute_command" and len(sys.argv) >= 4:
            test_tool("execute_command", {"command": sys.argv[3]})
        elif tool_name == "take_screenshot":
            test_tool("take_screenshot", {})
        else:
            print(f"✕ Unknown tool: {tool_name}")

    elif sys.argv[1] == "url":
        try:
            url = discover_mcp_server_url(logger)
            print(f"Ngrok URL: {url}")
        except Exception as e:
            print(f"✕ Could not get ngrok URL: {e}")

    else:
        print("Usage: python3 test_mcp_tools.py [list|test|url]")


if __name__ == "__main__":
    main()
