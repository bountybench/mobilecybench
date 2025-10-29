#!/usr/bin/env python3
"""
Direct MCP Tool Executor
Reads commands from .txt file and executes them against MCP server.
Format: tool,command or just command (defaults to execute_command)
"""

import argparse
import json
import logging
from datetime import datetime

import requests

from utils.mcp_utils import check_server_health, discover_ngrok_base_url


class MCPToolExecutor:
    def __init__(self, ngrok_base_url: str = None):
        # Setup logging to file first
        log_filename = f"mcp_executor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        logging.basicConfig(
            filename=log_filename,
            level=logging.DEBUG,
            format="%(asctime)s - %(levelname)s - %(message)s",
            filemode="w",
        )
        self.logger = logging.getLogger(__name__)
        print(f"Verbose logs written to: {log_filename}")

        if ngrok_base_url:
            self.ngrok_base_url = ngrok_base_url.rstrip("/")
            print(f"Using provided ngrok base URL: {self.ngrok_base_url}")
        else:
            try:
                self.ngrok_base_url = discover_ngrok_base_url(self.logger)
            except Exception as e:
                print("Failed to discover ngrok URL, falling back to localhost:8000")
                self.logger.error(f"Failed to discover ngrok URL: {e}")
                self.ngrok_base_url = "http://localhost:8000"

        # Construct the full MCP server URL
        self.mcp_server_url = f"{self.ngrok_base_url}/mcp"

        self.session = requests.Session()
        # Set required headers for FastMCP Streamable HTTP transport
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
        )

        self._request_id = 0

    def check_server(self) -> bool:
        """Check if MCP server is running and accessible"""
        print("Checking MCP server connectivity...")

        if not check_server_health(self.ngrok_base_url, timeout=5):
            print(f"❌ Cannot connect to MCP server at {self.mcp_server_url}")
            print(f"   (ngrok base URL: {self.ngrok_base_url})")
            print("\nTroubleshooting steps:")
            print("1. Check if MCP server container is running:")
            print("   docker ps | grep mcp-server")
            print("2. Start the MCP server if not running:")
            print("   docker compose up -d mcp-server")
            print("3. Check server logs:")
            print("   docker logs mcp-server")
            print("4. Verify server is listening on port 8000:")
            print("   curl -v http://localhost:8000/mcp")
            return False

        print("✅ MCP server is accessible")
        return True

    def list_tools(self) -> list[str]:
        """List available tools from the MCP server"""
        if not self.check_server():
            raise RuntimeError(f"Cannot connect to MCP server at {self.mcp_server_url}")

        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/list",
            "params": {},
        }
        try:
            response = self.session.post(self.mcp_server_url, json=payload, timeout=30)
            response.raise_for_status()

            if response.headers.get("content-type", "").startswith("text/event-stream"):
                # Parse Server-Sent Events format
                lines = response.text.strip().split("\n")
                for line in lines:
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        try:
                            data = json.loads(data_str)
                            tools = data["result"]["tools"]
                            self.logger.info(
                                f"✓ Found {len(tools)} tool{'' if len(tools) == 1 else 's'}:"
                            )
                            self.logger.info(f"Tools: {json.dumps(tools, indent=2)}")
                            return tools
                        except Exception:
                            continue
                raise ValueError("No data found in Server-Sent Events response")
            else:
                return response.json()
        except Exception as e:
            self.logger.error(f"Failed to list tools: {e}")
            return {"error": f"Failed to list tools: {e}"}

    def call_tool(self, tool_name: str, command: str, experiment_id: str) -> dict:
        """Execute tool via MCP JSON-RPC with experiment_id for routing"""
        if not self.check_server():
            raise RuntimeError(f"Cannot connect to MCP server at {self.mcp_server_url}")

        self._request_id += 1
        # Include experiment_id in arguments for MCP server routing
        arguments = {"command": command, "experiment_id": experiment_id}
            
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        try:
            response = self.session.post(self.mcp_server_url, json=payload, timeout=30)
            response.raise_for_status()

            # Handle streaming response from FastMCP
            if response.headers.get("content-type", "").startswith("text/event-stream"):
                # Parse Server-Sent Events format
                lines = response.text.strip().split("\n")
                for line in lines:
                    if line.startswith("data: "):
                        self.logger.info(f"Response: {line[6:]}")
                        return json.loads(line[6:])  # Remove 'data: ' prefix
            else:
                return response.json()

        except Exception as e:
            return {"error": str(e)}

    def parse_line(self, line: str) -> tuple[str, str]:
        """Parse line into tool and command. Default tool is execute_command."""
        line = line.strip()
        if not line:
            return None, None

        if "," in line:
            tool, command = line.split(",", 1)
            return tool.strip(), command.strip()
        else:
            return "execute_command", line

    def execute_from_file(self, filepath: str, experiment_id: str):
        """Execute commands from text file"""
        # Check server connectivity first
        if not self.check_server():
            raise RuntimeError(f"Cannot connect to MCP server at {self.mcp_server_url}")

        try:
            with open(filepath, "r") as f:
                lines = f.readlines()
        except FileNotFoundError:
            print(f"Error: File {filepath} not found")
            return

        print(f"Executing commands from: {filepath}")
        print("=" * 50)

        for i, line in enumerate(lines, 1):
            tool_name, command = self.parse_line(line)

            if not command:
                continue

            print(f"[{i}] {tool_name}: {command}")
            self.logger.info(
                f"Executing command {i}/{len(lines)}: {tool_name} - {command}"
            )
            result = self.call_tool(tool_name, command, experiment_id)

            # Log full response details
            self.logger.debug(
                f"Full response for command {i}: {json.dumps(result, indent=2)}"
            )

            if "error" in result:
                print(f"    ❌ ERROR: {result['error']}")
                self.logger.error(f"Command {i} failed: {result['error']}")
            elif "result" in result and "structuredContent" in result["result"]:
                # Extract just the command response, not the UI elements
                structured = result["result"]["structuredContent"]
                if "response" in structured:
                    print(f"    {structured['response']}")
                    self.logger.info(f"Command {i} completed successfully")
                else:
                    print(f"    {result}")
                    self.logger.warning(f"Unexpected response format for command {i}")
            else:
                print(f"    {result}")
                self.logger.warning(f"Unexpected response format for command {i}")

            print()


def main():
    parser = argparse.ArgumentParser(description="Execute MCP tools from text file")
    parser.add_argument("file", nargs="?", help="Text file with commands")
    parser.add_argument(
        "--show-url", action="store_true", help="Show the discovered ngrok URL"
    )
    parser.add_argument(
        "--check-health", action="store_true", help="Check the health of the MCP server"
    )
    parser.add_argument(
        "--list-tools", action="store_true", help="List available tools"
    )
    parser.add_argument("--call-tool", help="Name of the tool to call")
    parser.add_argument(
        "--args", help="Arguments for the tool (defaults to execute_command)"
    )
    parser.add_argument(
        "--experiment-id",
        help="Experiment ID used for routing to the correct Kali container (required for tool calls and file execution)",
    )
    args = parser.parse_args()

    executor = MCPToolExecutor()
    if args.show_url:
        try:
            print(f"Ngrok URL: {executor.ngrok_base_url}")
            print(f"MCP Server URL: {executor.mcp_server_url}")
        except Exception as e:
            print(f"❌ ERROR: Could not get ngrok URL: {e}")
    elif args.check_health:
        if executor.check_server():
            print("✅ MCP server is accessible")
        else:
            print("❌ MCP server is not accessible")
    elif args.list_tools:
        tools = executor.list_tools()
        if "error" in tools:
            print(f"❌ ERROR: {tools['error']}")
        elif tools:
            print(f"✓ Found {len(tools)} tool{'' if len(tools) == 1 else 's'}:")
            for i, tool in enumerate(tools, 1):
                print(f"{i}. {tool['name']}")
                print(f"   Description: {tool['description']}")
                if "inputSchema" in tool and "properties" in tool["inputSchema"]:
                    params = list(tool["inputSchema"]["properties"].keys())
                    if params:
                        print(f"   Parameters: {', '.join(params)}")
    elif args.call_tool:
        tool_name = args.call_tool
        tool_arguments = args.args or ""

        print(f"Calling tool: {tool_name}")
        if tool_arguments:
            print(f"Arguments: {tool_arguments}")
        print("=" * 50)

        if not args.experiment_id:
            print("❌ ERROR: --experiment-id is required for calling tools")
            return

        result = executor.call_tool(tool_name, tool_arguments, args.experiment_id)
        # Format the output nicely - only show response content, not UI elements
        if "error" in result:
            print(f"❌ ERROR: {result['error']}")
        elif "result" in result and "structuredContent" in result["result"]:
            # Extract just the response from structuredContent
            response = result["result"]["structuredContent"].get("response", "")
            print(f"✅ Tool response: {response}")
        else:
            print(f"✅ Tool response: {result}")
    else:
        if not args.file:
            parser.print_help()
            return
        if not args.experiment_id:
            print("❌ ERROR: --experiment-id is required when executing from file")
            return
        executor.execute_from_file(args.file, args.experiment_id)


if __name__ == "__main__":
    main()
