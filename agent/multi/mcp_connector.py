"""
Adapter to convert MCP config to LangChain tools.
This allows the multi-agent system to use your existing MCP server.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import requests
from langchain_core.tools import tool

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.mcp_utils import get_mcp_server_config


def create_langchain_tools_from_mcp(mcp_config: Dict[str, Any] = None) -> List:
    """
    Create LangChain tools from MCP server configuration.

    Args:
        mcp_config: MCP configuration dict. If None, auto-discovers from ngrok.

    Returns:
        List of LangChain tools that call the MCP server
    """
    if mcp_config is None:
        mcp_config = get_mcp_server_config(check_reachability=True)

    server_url = mcp_config["server_url"]

    # Create tools using @tool decorator
    @tool
    def execute_command(command: str) -> str:
        """Execute a terminal command in the Android testing environment.

        Use this to:
        - Run adb commands to test Android app: adb shell content query, adb shell am start
        - Execute curl commands to test server endpoints: curl -i http://server:8080/api
        - Read files: cat, head, grep
        - Search code: grep -r, find
        - Test exploits and capture output

        Args:
            command: The bash command to execute

        Returns:
            Command output including exit code and stdout/stderr
        """
        return call_mcp_tool(server_url, "execute_command", {"command": command})

    @tool
    def get_current_ui_state() -> Dict[str, Any]:
        """Get the current UI state of the Android emulator.

        Returns a dictionary containing:
        - ui_elements: List of interactive UI elements with text and coordinates
        - screen_description: Text description of what's visible

        Use this to:
        - Check if an activity launched successfully
        - Verify UI changes after exploitation
        - Find clickable elements for interaction

        Returns:
            Dictionary with UI state information
        """
        result = call_mcp_tool(server_url, "get_current_ui_state", {})
        # Parse JSON if it's a string
        if isinstance(result, str):
            try:
                return json.loads(result)
            except:
                return {"error": "Failed to parse UI state", "raw": result}
        return result

    return [execute_command, get_current_ui_state]


def call_mcp_tool(server_url: str, tool_name: str, arguments: Dict[str, Any]) -> Any:
    """
    Call an MCP tool via HTTP using JSON-RPC protocol.

    Args:
        server_url: MCP server URL (e.g., https://abc.ngrok.io/mcp/)
        tool_name: Name of the tool to call
        arguments: Tool arguments as dictionary

    Returns:
        Tool result
    """
    # FastMCP uses JSON-RPC 2.0 protocol
    # POST to /mcp endpoint with JSON-RPC format

    try:
        # server_url should already be the full MCP endpoint (e.g., https://xxx.ngrok.io/mcp/)
        # Just ensure it doesn't have a trailing slash for the POST
        server_url = server_url.rstrip("/")

        # Build JSON-RPC payload
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        response = requests.post(
            server_url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            timeout=300,  # 5 minutes for long-running commands
        )

        response.raise_for_status()

        # Handle Server-Sent Events (streaming) or JSON response
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            # Parse Server-Sent Events format
            lines = response.text.strip().split("\n")
            for line in lines:
                if line.startswith("data: "):
                    result = json.loads(line[6:])  # Remove 'data: ' prefix
                    break
            else:
                return "Error: No data found in streaming response"
        else:
            result = response.json()

        # Extract the actual content from JSON-RPC response
        if isinstance(result, dict):
            # Check for JSON-RPC error
            if "error" in result:
                return f"MCP Error: {result['error']}"

            # Extract result from JSON-RPC response
            if "result" in result:
                rpc_result = result["result"]

                # Check for structuredContent (FastMCP format)
                if isinstance(rpc_result, dict) and "structuredContent" in rpc_result:
                    structured = rpc_result["structuredContent"]
                    if "result" in structured:
                        return structured["result"]
                    return str(structured)

                # Check for content list
                if isinstance(rpc_result, dict) and "content" in rpc_result:
                    content = rpc_result["content"]
                    if isinstance(content, list) and len(content) > 0:
                        # MCP returns content as list of dicts with 'text' field
                        if isinstance(content[0], dict) and "text" in content[0]:
                            return content[0]["text"]
                        return content[0]
                    return content

                return rpc_result

        return result

    except requests.exceptions.RequestException as e:
        return f"Error calling MCP tool {tool_name}: {str(e)}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"


if __name__ == "__main__":
    """Test the MCP adapter"""
    print("Testing MCP adapter...")

    try:
        # Get MCP config
        print("\n[1/3] Discovering MCP server...")
        mcp_config = get_mcp_server_config()
        print(f"  MCP Server: {mcp_config['server_url']}")

        # Create tools
        print("\n[2/3] Creating LangChain tools...")
        tools = create_langchain_tools_from_mcp(mcp_config)
        print(f"  Created {len(tools)} tools:")
        for t in tools:
            print(f"    - {t.name}: {t.description[:60]}...")

        # Test execute_command
        print("\n[3/3] Testing execute_command tool...")
        result = tools[0].invoke({"command": "pwd"})
        print(f"  Result: {result[:200]}...")

        print("\n[SUCCESS] MCP adapter working!")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback

        traceback.print_exc()
