# MCP Tools Tester

A simple script to test MCP server tools via Docker container.

## Usage

```bash
# List all available tools
python3 test_mcp_tools.py

# List tools (explicit)
python3 test_mcp_tools.py list

# Test a tool
python3 test_mcp_tools.py test execute_command "adb devices"
python3 test_mcp_tools.py test take_screenshot

# Get ngrok URL
python3 test_mcp_tools.py url
```

## Features

- ✅ Lists all available MCP tools
- ✅ Tests individual tools
- ✅ Shows tool parameters
- ✅ Gets ngrok URL for external access
- ✅ Uses Docker exec (no external dependencies)
- ✅ Handles Server-Sent Events properly

## Requirements

- MCP server running in Docker container
- Docker accessible from command line
