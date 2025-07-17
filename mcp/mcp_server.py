import asyncio
import subprocess
import docker
from mcp.server import Server
from mcp.types import Tool, TextContent
import json

class MobileCyberMCPServer:
    def __init__(self):
        self.server = Server("mobile-cyber-mcp")
        self.docker_client = docker.from_env()
        self.kali_container_name = "kali-container"
        self.emulator_host = "host.docker.internal"
        self.emulator_port = "5554"  # Default Android emulator port
        
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
                    description="Execute ADB command to interact with emulator",
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
                    name="check_emulator_status",
                    description="Check if the Android emulator is running and accessible",
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
            
            elif name == "check_emulator_status":
                return await self.check_emulator_status()
            
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

    async def execute_kali_command(self, command: str):
        """Execute command in Kali Linux container"""
        try:
            # Get the Kali container
            kali_container = self.docker_client.containers.get(self.kali_container_name)
            
            # Execute command
            result = kali_container.exec_run(
                cmd=f"bash -c '{command}'",
                stdout=True,
                stderr=True
            )
            
            output = result.output.decode('utf-8')
            exit_code = result.exit_code
            
            return [TextContent(
                type="text",
                text=f"Exit Code: {exit_code}\nOutput:\n{output}"
            )]
            
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error executing command in Kali: {str(e)}"
            )]

    async def execute_adb_command(self, command: str):
        """Execute ADB command to interact with emulator"""
        try:
            kali_container = self.docker_client.containers.get(self.kali_container_name)
            
            # For emulator started with your script, we typically don't need explicit connect
            # The emulator should be auto-detected by adb
            full_command = f"adb {command}"
            result = kali_container.exec_run(
                cmd=f"bash -c '{full_command}'",
                stdout=True,
                stderr=True
            )
            
            output = result.output.decode('utf-8')
            exit_code = result.exit_code
            
            return [TextContent(
                type="text",
                text=f"ADB Command: {full_command}\nExit Code: {exit_code}\nOutput:\n{output}"
            )]
            
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error executing ADB command: {str(e)}"
            )]

    async def check_emulator_status(self):
        """Check emulator connectivity"""
        try:
            kali_container = self.docker_client.containers.get(self.kali_container_name)
            
            # Check devices and emulator status
            result = kali_container.exec_run(
                cmd=f"bash -c 'adb devices -l && echo \"--- Emulator Info ---\" && adb shell getprop ro.build.version.release 2>/dev/null || echo \"Emulator not responding\"'",
                stdout=True,
                stderr=True
            )
            
            output = result.output.decode('utf-8')
            
            return [TextContent(
                type="text",
                text=f"Emulator Status:\n{output}"
            )]
            
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error checking emulator status: {str(e)}"
            )]

async def main():
    """Start the MCP server"""
    server_instance = MobileCyberMCPServer()
    
    # Run the server
    from mcp.server.stdio import stdio_server
    async with stdio_server() as streams:
        await server_instance.server.run(
            streams[0], streams[1],
            server_instance.server.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())