# MobileCybench AI Agent

## Table of Contents
1. [Quick Health Check](#quick-health-check)
2. [Overview](#overview)
3. [Directory Structure](#directory-structure)
4. [Prerequisites](#prerequisites)
5. [Agent Environment Setup](#agent-environment-setup)
6. [Testing the Agent](#testing-the-agent)
7. [Running the Agent](#running-the-agent)
8. [Troubleshooting](#troubleshooting)

## Quick Health Check

Verify the MCP server is responding:

```bash
docker exec mcp-server curl http://localhost:4040/api/tunnels
```

This should return JSON with tunnel information including the public ngrok URL. If it doesn't, look through the following instructions to ensure your setup is correct. 

## Overview

The MobileCybench AI Agent enables an LM agent to perform security testing of Android applications. It consists of multiple Docker containers that work together to provide:

- **MCP Server**: Model Context Protocol server for tool execution
- **Kali Container**: Security testing environment with penetration testing tools
- **Ngrok Tunnel**: Secure external connectivity for AI agent communication
- **Custom Agent**: AI agent that interacts with Android apps and security tools

## Directory Structure

```
agent/
├── README.md                    
├── docker-compose.yml           # Orchestrates MCP server and Kali containers
├── custom_agent.py              # Main AI agent implementation
├── setup_env.sh                 # Environment setup script
├── kali/                        # Kali Linux container configuration
│   └── Dockerfile              # Kali container build instructions
└── mcp/                        
    ├── mcp_server.py           # MCP server implementation
    ├── direct_tool_executor.py # Tool execution interface
    ├── ui_connection.py        # UI connection handling
    ├── docker_setup.py         # Docker setup utilities
    ├── Dockerfile              # MCP container build instructions
    ├── ngrok.yml               # Ngrok tunnel configuration
    └── example_commands.txt    # Example commands for testing
```

## Prerequisites

Before setting up the agent environment, ensure you have:

- **Docker Desktop** installed and running
- **Python 3.11+** with virtual environment support
- **OpenAI API Key** for AI agent functionality (Reach out to Thomas or Nardos if you need one)
- **Ngrok Account** and auth token
- **Android SDK** and emulator setup (handled by main project)

## Agent Environment Setup

### 1. Ngrok Configuration

**Important**: The `ngrok.yml` file is not tracked by git (for security reasons) and must be created from the template.

1. **Get your ngrok token:**
   - Go to [https://ngrok.com](https://ngrok.com) and sign up
   - Get your auth token from the dashboard

2. **Create the ngrok configuration file from template:**
   ```bash
   # Copy the template to create your ngrok.yml file
   cp agent/mcp/ngrok.yml.template agent/mcp/ngrok.yml
   ```

3. **Edit the file and add your actual token:**
   ```bash
   # Replace YOUR_NGROK_AUTHTOKEN_HERE with your actual token
   nano agent/mcp/ngrok.yml
   # or
   code agent/mcp/ngrok.yml
   ```

   The file should look like:
   ```yaml
   version: 2
   authtoken: {YOUR_AUTH_TOKEN_HERE}
   tunnels:
     web:
       proto: http
       addr: 8000
   ```

### 2. Python Environment Setup

Make sure you're on Python 3.12 or lower for dependency compatibility.

Set up the Python virtual environment and install dependencies:

```bash
# From the project root directory (mobilecybench/)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. API Key Configuration

Create the environment file for your OpenAI API key:

```bash
# From the project root directory
echo "OPENAI_API_KEY=your_actual_api_key_here" > agent/.env
```

Or set it as an environment variable:
```bash
export OPENAI_API_KEY="sk-your-actual-openai-api-key-here"
```

### 4. Start Agent Containers

Start the agent Docker containers:

```bash
# From the project root directory
cd agent/
docker-compose up --build -d
```

This will start:
- **mcp-server**: MCP server with ngrok tunnel
- **kali-container**: Kali Linux environment with security tools

### 5. Verify Container Status

Check that all containers are running:

```bash
docker ps
```

You should see:
- `mcp-server` (port 8000)
- `kali-container`
- `mobilecybench-backend` (from main project)

## Testing the Agent

### 1. Basic Agent Test

Test the AI agent interaction:

```bash
# From the project root directory
source .venv/bin/activate
python test_ai_interaction.py
```

Expected output:
```
quit to quit, Give a command to the agent... 
```

### 2. Using Example Commands

The `mcp/example_commands.txt` file contains sample commands you can use to test the agent. Try these commands:

**Android Device Commands:**
- `adb devices` - List connected Android devices
- `adb shell getprop ro.build.version.release` - Get Android version
- `adb shell pm list packages | head -5` - List first 5 installed packages

**Kali Container Commands:**
- `execute_command,whoami` - Check current user in Kali container
- `execute_command,pwd` - Show current directory in Kali container
- `execute_command,ls -la /tmp` - List files in /tmp directory

## Running the Agent

### Full Pipeline Mode

For complete automated testing with the runner:

```bash
# From the project root directory
source .venv/bin/activate
python runner.py apps/<app_name>
# or
python runner.py <app_name>
```

Example:
```bash
python runner.py apps/conversations
```

This runs the complete pipeline:
1. Sets up Android emulator
2. Builds and installs the target app
3. Runs initial security checks
4. Starts the AI agent
5. Executes AI-driven security testing
6. Runs final security validation
