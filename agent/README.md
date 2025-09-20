# MobileCybench AI Agent

## Table of Contents
1. [Quick Health Check](#quick-health-check)
2. [Overview](#overview)
3. [Codex CLI Agent Setup](#codex-cli-agent-setup)
4. [Directory Structure](#directory-structure)
5. [Prerequisites](#prerequisites)
6. [Agent Environment Setup](#agent-environment-setup)
7. [Testing the Agent](#testing-the-agent)
8. [Running the Agent](#running-the-agent)
9. [Troubleshooting](#troubleshooting)

## Quick Health Check

Verify the containerized environment is working:

```bash
# Check if containers are running
docker ps

# Verify MCP server is responding
curl http://localhost:8000/mcp

# Test ADB connectivity to emulator
docker exec mcp-server adb devices
```

You should see the `codex-agent`, `mcp-server`, and `kali-container` running, MCP server responding with JSON, and your emulator listed as a connected device. 

## Overview

The MobileCybench AI Agent enables an LM agent to perform security testing of Android applications. It consists of multiple Docker containers that work together to provide:

- **MCP Server**: Model Context Protocol server for tool execution
- **Kali Container**: Security testing environment with penetration testing tools
- **Ngrok Tunnel**: Secure external connectivity for AI agent communication
- **Custom Agent**: AI agent that interacts with Android apps and security tools

## Containerized Codex Agent Setup

### Current Implementation

The MobileCybench agent now uses a **containerized Codex CLI architecture** that provides complete isolation and simplified setup for Android security testing. This eliminates the need for manual configuration and provides a secure, reproducible testing environment.

### Architecture Overview

The containerized setup consists of three containers:

- **codex-agent**: Runs Codex CLI with the target app's source code
- **mcp-server**: Provides MCP (Model Context Protocol) tools for Android testing
- **kali-container**: Security testing environment with penetration testing tools

All containers communicate via an isolated Docker network without external dependencies.

### Prerequisites

Before running the containerized Codex agent, ensure you have:

- **Docker** installed and running
- **Python 3.11+**
- **OpenAI API Key** (contact team if you need one)
- **Android Emulator** running on the host (for dynamic testing)

### Quick Start

#### 1. Set API Key

Set your OpenAI API key as an environment variable:

```bash
export OPENAI_API_KEY="sk-your-actual-openai-api-key-here"
```

Or create an environment file:
```bash
# From the project root directory
echo "OPENAI_API_KEY=your_actual_api_key_here" > .env
```

#### 2. Run Containerized Agent

Execute the containerized Codex agent with a single command:

```bash
# From project root directory
python3 agent/runner_containerized.py --app termux
```

Replace `termux` with any supported app name (e.g., `joplin`, `bitwarden`, `nextcloud-talk`).

#### 3. What Happens Automatically

The containerized runner will automatically:

1. **Build containers** - Creates codex-agent, mcp-server, and kali-container
2. **Start services** - Launches all containers with proper networking
3. **Setup app** - Builds the target app APK and installs it on the emulator
4. **Run analysis** - Executes Codex CLI for comprehensive security testing
5. **Extract logs** - Saves analysis results to `./logs/` directory
6. **Cleanup** - Stops and removes containers when finished

### Container Details

#### Codex Agent Container (`codex-agent`)
- **Purpose**: Runs Codex CLI with app source code
- **Base**: Ubuntu 22.04 with Node.js 20 and Codex CLI
- **Security**: No privileged access, no host volumes mounted
- **Configuration**: Pre-configured TOML for MCP integration

#### MCP Server Container (`mcp-server`)
- **Purpose**: Provides Android testing tools via MCP protocol
- **Base**: Python 3.11 with FastMCP and Android tools
- **Network**: Connects to host emulator via `host.docker.internal:5037`
- **Tools**: ADB commands, file operations, security utilities

#### Kali Container (`kali-container`)
- **Purpose**: Security testing environment
- **Base**: `cybench/mobilecybench:latest` with penetration testing tools
- **Access**: Available for advanced security tool execution
- **Privileges**: Privileged access for security tools

### Advanced Usage

#### Custom Configuration

For advanced users, you can modify container behavior:

```bash
# Run with custom iteration limit
python3 agent/runner_containerized.py --app termux --max-iterations 20

# Run in dry-run mode to see what would be executed
python3 agent/runner_containerized.py --app termux --dry-run
```

#### Manual Container Management

For debugging, you can manually manage containers:

```bash
# Start containers manually
APP_NAME=termux docker compose -f agent/docker-compose-isolated.yml up -d

# Check container status
docker ps

# View logs
docker logs codex-agent
docker logs mcp-server

# Stop containers
docker compose -f agent/docker-compose-isolated.yml down
```

### Security Features

- **Complete Isolation**: Containers run without host filesystem access
- **Network Isolation**: Internal Docker network for container communication
- **API Key Security**: Environment variables, no hardcoded credentials
- **Minimal Privileges**: Only mcp-server and kali-container have required privileges
- **No External Dependencies**: No ngrok or external tunnel requirements

### Troubleshooting

#### Common Issues

**Container Build Failures:**
```bash
# Clean Docker cache and rebuild
docker system prune -f
python3 agent/runner_containerized.py --app termux
```

**ADB Connection Issues:**
```bash
# Verify emulator is running
adb devices

# Check if emulator is accessible from containers
docker exec mcp-server adb devices
```

**API Key Issues:**
```bash
# Verify API key is set
echo $OPENAI_API_KEY

# Check container environment
docker exec codex-agent env | grep OPENAI_API_KEY
```

### Log Files

Analysis results are automatically saved to:

- `./logs/agent_run_YYYYMMDD_HHMMSS.log` - Complete agent execution log
- `./logs/mobile_security_analysis.log` - Tool interaction log

## Directory Structure

```
agent/
├── README.md                    # This documentation
├── docker-compose-isolated.yml # Containerized environment orchestration
├── runner_containerized.py     # Containerized Codex agent runner
├── codex_agent.py              # Codex CLI integration
├── codex_cli_provider.py       # Codex CLI provider implementation
├── codex_prompts.py            # Security testing prompts
├── codex/                      # Codex CLI container configuration
│   ├── Dockerfile              # Codex agent container build
│   └── config.toml             # Pre-configured Codex CLI settings
└── mcp/                        # MCP server container
    ├── mcp_server.py           # FastMCP server implementation
    ├── mcp_proxy.py            # MCP proxy for container communication
    ├── ui_connection.py        # Android UI interaction handling
    ├── docker_setup.py         # Docker container utilities
    ├── Dockerfile              # MCP container build instructions
    └── ngrok.yml               # Legacy ngrok configuration (not used)
```

## Prerequisites

Before setting up the agent environment, ensure you have:

- **Docker Desktop** installed and running
- **Python 3.11+**
- **OpenAI API Key** for AI agent functionality (Reach out to Thomas or Nardos if you need one)
- **Android SDK** and emulator setup (handled by main project)

**Note**: The containerized setup eliminates the need for ngrok, manual FastMCP server setup, or complex configuration files.

## Legacy Agent Environment Setup (Host-based)

**Note**: This section is for the legacy host-based setup. The containerized setup (recommended) handles all configuration automatically.

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

Set up the Python virtual environment and install dependencies:

```bash
# From the project root directory (mobilecybench/)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
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

## Testing the Agent (Legacy Host-based)

**Note**: For containerized testing, simply run `python3 agent/runner_containerized.py --app <app_name>`. This section covers legacy host-based testing.

### 1. Basic Agent Test

Test the AI agent interaction:

```bash
# From the project root directory
source venv/bin/activate
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

### Containerized Mode (Recommended)

For complete automated testing with the containerized runner:

```bash
# From the project root directory
python3 agent/runner_containerized.py --app <app_name>
```

Example:
```bash
python3 agent/runner_containerized.py --app termux
```

This runs the complete containerized pipeline:
1. Builds and starts isolated Docker containers
2. Sets up target app (builds APK and installs on emulator)
3. Configures secure container-to-container networking
4. Starts Codex CLI agent with pre-configured MCP tools
5. Executes AI-driven security testing
6. Extracts logs and results automatically
7. Cleans up containers when finished

### Legacy Host-based Mode

For backwards compatibility, the original host-based runner is still available:

```bash
# From the project root directory
source venv/bin/activate
python runner.py <app_name> --agent codex
```

**Note**: The containerized mode is recommended for better security isolation and simplified setup.