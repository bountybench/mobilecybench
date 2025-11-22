# MobileCybench AI Agent

## Table of Contents
1. [Quick Health Check](#quick-health-check)
2. [Overview](#overview)
3. [Directory Structure](#directory-structure)
4. [Utils Dependencies](#utils-dependencies)
5. [Prerequisites](#prerequisites)
6. [Agent Environment Setup](#agent-environment-setup)
7. [Testing the Agent](#testing-the-agent)
8. [Running the Agent](#running-the-agent)
9. [Troubleshooting](#troubleshooting)

## Quick Health Check

Verify the MCP server is responding:
# TODO - update this to 

```bash
docker exec mcp-server curl http://localhost:4040/api/tunnels
```

**Note**: This command will only work after the agent containers are running and ngrok is properly configured (see [Agent Environment Setup](#agent-environment-setup) below). If you haven't set up the environment yet, you'll get connection errors - this is expected.

This should return JSON with tunnel information including the public ngrok URL. If it doesn't work after ngrok setup, look through the following instructions to ensure your setup is correct. 

## Overview

The MobileCybench AI Agent enables an LM agent to perform security testing of Android applications. It consists of multiple Docker containers that work together to provide:

- **MCP Server**: Model Context Protocol server for tool execution
- **Kali Container**: Security testing environment with penetration testing tools
- **Ngrok Tunnel**: Secure external connectivity for AI agent communication
- **Custom Agent**: AI agent that interacts with Android apps and security tools
- **Time Tracking**: Comprehensive timing and performance monitoring
- **Model Providers**: Flexible AI model provider architecture
- **Token Tracking**: Cost and usage monitoring for AI API calls 

## Directory Structure

```
agent/
├── README.md                    
├── docker-compose.yml           # Orchestrates MCP server and Kali containers
├── custom_agent.py              # Main AI agent implementation
├── agent_setup.py               # Agent environment setup and configuration
├── kali/                        # Kali Linux container configuration
│   ├── Dockerfile              # Kali container build instructions
│   └── Dockerfile.kali         # Alternative Kali container setup
├── mcp/                        
│   ├── mcp_server.py           # MCP server implementation
│   ├── direct_tool_executor.py # Tool execution interface
│   ├── ui_connection.py        # UI connection handling
│   ├── docker_setup.py         # Docker setup utilities
│   ├── Dockerfile              # MCP container build instructions
│   ├── ngrok.yml               # Ngrok tunnel configuration (created from template)
│   ├── ngrok.yml.template      # Template for ngrok configuration
│   ├── example_commands.txt    # Example commands for testing
│   └── screenshots/            # Screenshot storage directory
├── model_providers/            # AI model provider implementations
│   ├── __init__.py
│   ├── base.py                 # Base provider interface
│   ├── factory.py              # Provider factory pattern
│   └── openai_provider.py      # OpenAI API provider
└── prompts/                    # AI agent prompt templates
    ├── __init__.py
    └── prompts.py              # Prompt definitions and templates
```

## Utils Dependencies

The agent system relies on several utility modules for core functionality:

- **`utils.time_tracker`**: Comprehensive timing and performance monitoring
  - Tracks total experiment duration
  - Monitors individual LLM call times
  - Generates structured JSON timing reports
  - Provides statistics (p50, p95, p99) for performance analysis

- **`utils.token_tracker`**: AI API cost and usage monitoring
  - Tracks token usage across different models
  - Calculates costs based on current pricing
  - Provides usage summaries and totals

- **`utils.agent_utils`**: Agent-specific utility functions
  - Screenshot capture functionality
  - UI interaction helpers

- **`utils.mcp_utils`**: MCP server utilities
  - Server health checking
  - Ngrok URL discovery
  - MCP configuration management

- **`utils.logger`**: Centralized logging system
  - Structured logging for agent operations
  - Log file management
  - Different log levels for debugging

- **`utils.git_utils`**: Git repository utilities
  - Repository setup and configuration
  - Git operations for agent setup

## Prerequisites

Before setting up the agent environment, ensure you have:

- **Docker Desktop** installed and running
- **Python 3.11+** with virtual environment support
- **OpenAI API Key** for AI agent functionality (Reach out to Thomas or Nardos if you need one)
- **Ngrok Account** and auth token
- **Android SDK** and emulator setup (handled by main project)

## Agent Environment Setup

### 1. Ngrok Configuration

**Important**: The `ngrok.yml` file is not tracked by git (for security reasons) and must be created from the template. **This step is required before the Quick Health Check will work.**

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

### 5. Verify Container Status

Check that all containers are running:

```bash
docker ps
```

You should see:
- `mcp-server` (port 8000)
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
# Start the MCP server container from Step 4.
cd agent/
docker-compose up --build -d
cd ../
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
1. Initializes **kali-container**, the Kali Linux environment with security tools
2. Sets up Android emulator
3. Builds and installs the target app
4. Runs initial security checks (pre-agent-run probes)
5. Starts the AI agent with time tracking
6. Executes AI-driven security testing
7. Runs post-agent security validation (post-agent-run probes)
8. Checks for agent-generated exploit script (`/app/exploit_files/exploit.sh`)
9. If exploit found, restarts environment and executes exploit:
   - Runs `cleanup.sh` to reset the environment
   - Rebuilds and reinstalls the app
   - Runs pre-exploit probes
   - Executes the agent-generated exploit script
   - Runs post-exploit probes
10. Generates timing reports and performance statistics

### Time Tracking and Performance Monitoring

The agent now includes comprehensive timing and performance monitoring:

- **Experiment Duration**: Total time from start to completion
- **LLM Call Timing**: Individual API call durations with success/failure tracking
- **Performance Statistics**: p50, p95, p99 percentiles for latency analysis
- **JSON Reports**: Structured timing data saved as `timings_*.json` files
- **Cost Tracking**: Token usage and API costs per model

Timing data is automatically logged and saved for analysis and CI integration.

### Agent Exploit Execution Workflow

After the agent completes its security testing, the runner automatically checks for any exploit scripts generated by the agent. If an exploit script is found at `/app/exploit_files/exploit.sh` in the kali container, the following workflow is executed:

1. **Exploit Detection**: The runner checks if the agent created an exploit script
2. **Environment Reset**: 
   - Runs `cleanup.sh` to clean up Docker containers and reset the environment
   - Starts a fresh emulator instance
   - Rebuilds and reinstalls the app
3. **Pre-Exploit Baseline**: Runs security probes to establish a baseline state
4. **Exploit Execution**: 
   - Reads the exploit script contents
   - Executes the exploit script in the kali container
   - Captures all output (stdout, stderr, exit code) to a timestamped log file (`exploit_log_YYYYMMDD_HHMMSS.log`)
5. **Post-Exploit Validation**: Runs security probes again to detect any violations caused by the exploit

**Probe Results Tracking**: The runner tracks probe results at four key stages:
- `pre_agent_run`: Baseline before agent execution
- `post_agent_run`: After agent completes testing
- `pre_agent_exploit`: Baseline before exploit execution
- `post_agent_exploit`: After exploit execution

All probe results are stored in `runner.probe_results` dictionary and can be used for analysis and reporting.

## Troubleshooting

### Common Issues

**Time Tracking Issues:**
- If timing data is missing, check that `utils.time_tracker` is properly imported
- Verify that `time_tracker.start_experiment()` is called at the beginning of the run
- Check that `time_tracker.end_experiment()` is called in the finally block

**Model Provider Issues:**
- Ensure your OpenAI API key is correctly set in the environment
- Check that the model name matches the available models in your API plan
- Verify network connectivity to OpenAI's API endpoints

**Token Tracking Issues:**
- If cost calculations are incorrect, check the pricing data in `utils/token_costs.py`
- Verify that token usage is being recorded from API responses
- Ensure the model name matches the pricing configuration

**MCP Server Connection Issues:**
- Verify Docker containers are running: `docker ps`
- Check MCP server logs: `docker logs mcp-server`
- Ensure ngrok tunnel is active: `docker exec mcp-server curl http://localhost:4040/api/tunnels`
- **If container not found**: Run `docker-compose up --build -d` from the agent directory
- **If ngrok command fails**: Make sure you've completed the [Ngrok Configuration](#1-ngrok-configuration) step and created `ngrok.yml` from the template

**Agent Performance Issues:**
- Check timing logs for slow LLM calls
- Review JSON timing reports for performance bottlenecks
- Monitor token usage for cost optimization
