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

## Codex CLI Agent Setup

### Current Implementation

The MobileCybench agent now uses **Codex CLI** as the primary AI agent interface. This setup provides a localhost-only secure environment for Android security testing without requiring external tunnels or Docker networking.

### Prerequisites

Before setting up the Codex CLI agent, ensure you have:

- **Codex CLI** installed globally
- **OpenAI API Key** (contact team if you need one)
- **Python 3.11+** with virtual environment support
- **FastMCP server** running on localhost:8000

### Step-by-Step Setup from Fresh Clone

#### 1. Install Codex CLI

```bash
# Install Codex CLI globally
npm install -g @anthropic/codex
```

Verify installation:
```bash
codex --version
```

#### 2. Configure API Key

Create an environment file or set environment variable:

**Option A: Environment file (.env)**
```bash
# From the project root directory
echo "OPENAI_API_KEY=your_actual_api_key_here" > agent/.env
```

**Option B: Environment variable**
```bash
export OPENAI_API_KEY="sk-your-actual-openai-api-key-here"
```

#### 3. Create Codex CLI Configuration

Create the Codex CLI configuration file:

```bash
# Create config directory if it doesn't exist
mkdir -p ~/.codex

# Create config file
cat > ~/.codex/config.toml << 'EOF'
# Codex CLI Configuration for MobileCyberBench Android Security Agent
# Generated automatically - do not edit manually

# Model & Provider Settings
model = "codex-mini-latest"
model_provider = "openai-responses"

[model_providers.openai-responses]
name = "OpenAI using Responses API"
base_url = "https://api.openai.com/v1"
env_key = "OPENAI_API_KEY"
wire_api = "responses"
request_max_retries = 3
stream_max_retries = 5
stream_idle_timeout_ms = 300000

# Security Configuration
sandbox_mode = "read-only"
sandbox_permissions = ["filesystem-read", "process-read"]

# Sandbox Configuration
[sandbox_read_only]
network_access = false
exclude_tmpdir_env_var = false
exclude_slash_tmp = false

# Shell Environment Policy
[shell_environment_policy]
inherit = "core"
ignore_default_excludes = false
exclude = ["AWS_*", "AZURE_*", "GCP_*", "*_TOKEN", "*_SECRET", "*_KEY", "*_PASSWORD"]

[shell_environment_policy.set]
ANDROID_HOME = "/opt/android-sdk"
SECURITY_MODE = "read-only"

# MCP Servers for Android Security Testing
[mcp_servers.mobilecybench_tools]
command = "python3"
args = ["/home/ubuntu/Downloads/mobilecybench/agent/mcp/mcp_proxy.py"]
env = { "MCP_SERVER_URL" = "http://localhost:8000/mcp", "START_DIR" = "/tmp/termux_app" }
startup_timeout_ms = 60000
EOF
```

**Important**: Update the `args` path in the TOML file to match your actual clone location:
```bash
# Replace /home/ubuntu/Downloads/mobilecybench with your actual path
sed -i 's|/home/ubuntu/Downloads/mobilecybench|'$(pwd)'|g' ~/.codex/config.toml
```

#### 4. Start FastMCP Server

The agent requires a FastMCP server running on localhost:8000. Start it from the project root:

```bash
# From project root directory
cd agent/mcp
python3 -m fastmcp.server &
```

Verify the server is running:
```bash
curl http://localhost:8000/mcp
```

#### 5. Test Codex CLI Integration

Test that Codex CLI can communicate with the MCP proxy:

```bash
# Test basic Codex CLI functionality
codex exec "List the files in the current directory"

# Test MCP tool integration
codex exec "Use the execute_command tool to run 'adb devices'"
```

### Security Notes

- **API Key Security**: The `~/.codex/config.toml` file contains API key references but not the actual key
- **Localhost Only**: MCP server runs on localhost:8000 for security
- **Git Ignore**: API keys in `.env` files are already in `.gitignore`
- **Minimal Permissions**: Codex CLI runs with read-only sandbox permissions

### Required Files Summary

From a fresh clone, you need to create:

1. **`~/.codex/config.toml`** - Codex CLI configuration (shown above)
2. **`agent/.env`** - Environment file with OPENAI_API_KEY (optional, can use env var instead)
3. **FastMCP server running** - Start with `python3 -m fastmcp.server` in `agent/mcp/`

No other special files are required. The existing `mcp_proxy.py` and `codex_cli_provider.py` handle the integration.

### Testing the Setup

Verify your setup works by running:

```bash
# From project root
source venv/bin/activate
python runner.py termux --agent codex
```

This should start the Codex CLI agent and begin Android security testing.

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

## Testing the Agent

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

### Full Pipeline Mode

For complete automated testing with the runner:

```bash
# From the project root directory
source venv/bin/activate
python runner.py <app_name>
```

Example:
```bash
python runner.py joplin
```

This runs the complete pipeline:
1. Sets up Android emulator
2. Builds and installs the target app
3. Runs initial security checks
4. Starts the AI agent
5. Executes AI-driven security testing
6. Runs final security validation