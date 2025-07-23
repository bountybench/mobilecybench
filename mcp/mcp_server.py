#!/usr/bin/env python3

import asyncio
import json
import sys
import docker
from mcp.server import Server
from mcp.types import Tool, TextContent

class MobileCyberMCPServer:
    def __init__(self):
        self.server = Server("mobile-cyber-mcp")
        self.docker_client = docker.from_env()
        self.kali_container_name = "kali-container"
        self.host_adb_server = "host.docker.internal:5037"
        
        # Register tools
        self.register_tools()
    
    def register_tools(self):
        """Register available tools for the MCP server"""
        
        @self.server.list_tools()
        async def list_tools():
            return [
                Tool(
                    name="execute_kali_command",
                    description="Execute a command in the Kali Linux container",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "Command to execute in Kali container"
                            }
                        },
                        "required": ["command"]
                    }
                ),
                Tool(
                    name="adb_command",
                    description="Execute ADB command to interact with host emulator",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "ADB command to execute (without 'adb' prefix)"
                            }
                        },
                        "required": ["command"]
                    }
                ),
                Tool(
                    name="connect_to_host_adb",
                    description="Connect to the ADB server running on the host machine",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                ),
                Tool(
                    name="check_emulator_status",
                    description="Check if the Android emulator is running and accessible from host",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                )
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict):
            """Handle tool calls"""
            
            if name == "execute_kali_command":
                return await self.execute_kali_command(arguments["command"])
            
            elif name == "adb_command":
                return await self.execute_adb_command(arguments["command"])
            
            elif name == "connect_to_host_adb":
                return await self.connect_to_host_adb()
            
            elif name == "check_emulator_status":
                return await self.check_emulator_status()
            
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

    async def execute_kali_command(self, command: str):
        """Execute command in Kali Linux container"""
        try:
            kali_container = self.docker_client.containers.get(self.kali_container_name)
            
            result = kali_container.exec_run(
                cmd=f"bash -c '{command}'",
                stdout=True,
                stderr=True
            )
            
            output = result.output.decode('utf-8')
            exit_code = result.exit_code
            
            return [TextContent(
                type="text",
                text=f"Command: {command}\nExit Code: {exit_code}\nOutput:\n{output}"
            )]
            
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error executing command in Kali: {str(e)}"
            )]

    async def connect_to_host_adb(self):
        """Connect ADB in Kali container to host ADB server"""
        try:
            kali_container = self.docker_client.containers.get(self.kali_container_name)
            
            # Kill any existing ADB server in container
            result1 = kali_container.exec_run(
                cmd="bash -c 'adb kill-server'",
                stdout=True,
                stderr=True
            )
            
            # Connect to host ADB server
            result2 = kali_container.exec_run(
                cmd=f"bash -c 'export ADB_SERVER_SOCKET=tcp:{self.host_adb_server} && adb devices'",
                stdout=True,
                stderr=True
            )
            
            output = result2.output.decode('utf-8')
            
            return [TextContent(
                type="text",
                text=f"Host ADB Connection:\nKilled local ADB server\nConnected to host ADB at {self.host_adb_server}\nDevices found:\n{output}"
            )]
            
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error connecting to host ADB: {str(e)}"
            )]

    async def execute_adb_command(self, command: str):
        """Execute ADB command via host ADB server"""
        try:
            kali_container = self.docker_client.containers.get(self.kali_container_name)
            
            # Set environment to use host ADB server
            full_command = f"export ADB_SERVER_SOCKET=tcp:{self.host_adb_server} && adb {command}"
            result = kali_container.exec_run(
                cmd=f"bash -c '{full_command}'",
                stdout=True,
                stderr=True
            )
            
            output = result.output.decode('utf-8')
            exit_code = result.exit_code
            
            return [TextContent(
                type="text",
                text=f"ADB Command (via host): adb {command}\nExit Code: {exit_code}\nOutput:\n{output}"
            )]
            
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error executing ADB command via host: {str(e)}"
            )]

    async def check_emulator_status(self):
        """Check emulator status via host ADB"""
        try:
            kali_container = self.docker_client.containers.get(self.kali_container_name)
            
            # Check devices via host ADB
            result = kali_container.exec_run(
                cmd=f"bash -c 'export ADB_SERVER_SOCKET=tcp:{self.host_adb_server} && adb devices -l && echo \"--- Checking Emulator ---\" && adb shell getprop ro.build.version.release 2>/dev/null || echo \"No emulator responding\"'",
                stdout=True,
                stderr=True
            )
            
            output = result.output.decode('utf-8')
            
            return [TextContent(
                type="text",
                text=f"Emulator Status (via host ADB):\n{output}"
            )]
            
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error checking emulator status via host: {str(e)}"
            )]

async def main():
    """Start the MCP server"""
    server_instance = MobileCyberMCPServer()
    
    # Run the server with stdio
    from mcp.server.stdio import stdio_server
    
    async with stdio_server() as streams:
        await server_instance.server.run(
            streams[0], streams[1],
            server_instance.server.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())