#!/usr/bin/env python3
"""
Direct MCP Tool Executor
Reads commands from .txt file and executes them against MCP server.
Format: tool,command or just command (defaults to execute_command)
"""

import requests
import json
import subprocess
import argparse
import logging
from datetime import datetime


class MCPToolExecutor:
    def __init__(self, server_url: str = None):
        # Setup logging to file first
        log_filename = f"mcp_executor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        logging.basicConfig(
            filename=log_filename,
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            filemode='w'
        )
        self.logger = logging.getLogger(__name__)
        print(f"Verbose logs written to: {log_filename}")
        
        if server_url:
            self.server_url = server_url.rstrip('/')
            print(f"Using provided server URL: {self.server_url}")
        else:
            self.server_url = self.discover_ngrok_url()
        
        self.session = requests.Session()
        # Set required headers for FastMCP Streamable HTTP transport
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream'
        })
        
        self._request_id = 0
    
    def discover_ngrok_url(self) -> str:
        """Auto-discover the ngrok tunnel URL from the MCP server container"""
        try:
            self.logger.info("Attempting to discover ngrok URL...")
            result = subprocess.run(
                ["docker", "exec", "mcp-server", "curl", "http://localhost:4040/api/tunnels"],
                capture_output=True, text=True, check=True
            )
            self.logger.debug(f"Raw ngrok response: {result.stdout}")
            tunnels_data = json.loads(result.stdout)
            public_url = tunnels_data["tunnels"][0]["public_url"]
            print(f"Using ngrok URL: {public_url}")
            self.logger.info(f"Discovered ngrok URL: {public_url}")
            return public_url
        except Exception as e:
            print(f"Failed to discover ngrok URL, falling back to localhost:8000")
            self.logger.error(f"Failed to discover ngrok URL: {e}")
            return "http://localhost:8000"
    
    def parse_line(self, line: str) -> tuple[str, str]:
        """Parse line into tool and command. Default tool is execute_command."""
        line = line.strip()
        if not line:
            return None, None
            
        if ',' in line:
            tool, command = line.split(',', 1)
            return tool.strip(), command.strip()
        else:
            return 'execute_command', line
    
    def call_tool(self, tool_name: str, command: str) -> dict:
        """Execute tool via MCP JSON-RPC"""
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": {
                    "command": command
                }
            }
        }
        
        try:
            response = self.session.post(
                f"{self.server_url}/mcp",
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            
            # Handle streaming response from FastMCP
            if response.headers.get('content-type', '').startswith('text/event-stream'):
                # Parse Server-Sent Events format
                lines = response.text.strip().split('\n')
                for line in lines:
                    if line.startswith('data: '):
                        return json.loads(line[6:])  # Remove 'data: ' prefix
            else:
                return response.json()
                
        except Exception as e:
            return {"error": str(e)}
    
    def check_server(self) -> bool:
        """Check if MCP server is running and accessible"""
        try:
            # Try to list available tools to check connectivity
            self._request_id += 1
            response = self.session.post(
                f"{self.server_url}/mcp",
                json={"jsonrpc": "2.0", "id": self._request_id, "method": "tools/list"},
                timeout=5
            )
            return response.status_code == 200
        except Exception:
            return False
    
    def execute_from_file(self, filepath: str):
        """Execute commands from text file"""
        # Check server connectivity first
        print("Checking MCP server connectivity...")
        if not self.check_server():
            print(f"❌ Cannot connect to MCP server at {self.server_url}")
            print("\nTroubleshooting steps:")
            print("1. Check if MCP server container is running:")
            print("   docker ps | grep mcp-server")
            print("2. Start the MCP server if not running:")
            print("   docker compose up -d mcp-server")
            print("3. Check server logs:")
            print("   docker logs mcp-server")
            print("4. Verify server is listening on port 8000:")
            print("   curl -v http://localhost:8000/mcp")
            return
        
        print("✅ MCP server is accessible")
        
        try:
            with open(filepath, 'r') as f:
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
            self.logger.info(f"Executing command {i}/{len(lines)}: {tool_name} - {command}")
            result = self.call_tool(tool_name, command)
            
            # Log full response details
            self.logger.debug(f"Full response for command {i}: {json.dumps(result, indent=2)}")
            
            if 'error' in result:
                print(f"    ERROR: {result['error']}")
                self.logger.error(f"Command {i} failed: {result['error']}")
            elif 'result' in result and 'structuredContent' in result['result']:
                # Extract just the command response, not the UI elements
                structured = result['result']['structuredContent']
                if 'response' in structured:
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
    parser = argparse.ArgumentParser(description='Execute MCP tools from text file')
    parser.add_argument('file', help='Text file with commands')
    
    args = parser.parse_args()
    
    executor = MCPToolExecutor()
    executor.execute_from_file(args.file)


if __name__ == "__main__":
    main()