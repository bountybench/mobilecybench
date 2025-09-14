#!/usr/bin/env python3
"""
MCP Tools Checker - Simple Docker-based tool checker
"""

import json
import subprocess
import sys


def get_ngrok_url():
    """Get the ngrok URL from the running container"""
    try:
        cmd = "docker exec mcp-server curl -s http://localhost:4040/api/tunnels"
        result = subprocess.run(cmd.split(), capture_output=True, text=True)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data["tunnels"][0]["public_url"]
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def call_mcp_server(method, params=None):
    """Call MCP server via Docker container"""
    request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}

    cmd = [
        "docker",
        "exec",
        "mcp-server",
        "curl",
        "-X",
        "POST",
        "http://localhost:8000/mcp",
        "-H",
        "Content-Type: application/json",
        "-H",
        "Accept: application/json, text/event-stream",
        "-d",
        json.dumps(request),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            # Extract JSON from Server-Sent Events format
            lines = result.stdout.strip().split("\n")
            for line in lines:
                if line.startswith("data: "):
                    return json.loads(line[6:])
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def list_tools():
    """List available MCP tools"""
    print("🔍 MCP Server Tools")
    print("=" * 40)

    result = call_mcp_server("tools/list")
    if result and "result" in result and "tools" in result["result"]:
        tools = result["result"]["tools"]
        print(f"✅ Found {len(tools)} tools:\n")

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
        print("❌ No tools found or server not responding")
        return None


def test_tool(tool_name, arguments):
    """Test a specific tool"""
    print(f"🧪 Testing {tool_name}")
    print("-" * 30)

    result = call_mcp_server("tools/call", {"name": tool_name, "arguments": arguments})

    if result and "result" in result:
        print("✅ Success!")
        print(f"Result: {result['result']}")
    elif result and "error" in result:
        print(f"❌ Error: {result['error']}")
    else:
        print("❌ No response from server")


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
            print(f"❌ Unknown tool: {tool_name}")

    elif sys.argv[1] == "url":
        url = get_ngrok_url()
        if url:
            print(f"🌐 Ngrok URL: {url}")
        else:
            print("❌ Could not get ngrok URL")

    else:
        print("Usage: python3 test_mcp_tools.py [list|test|url]")


if __name__ == "__main__":
    main()
