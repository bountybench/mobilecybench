# MobileCybench AI Agent

## Table of Contents
1. [Overview](#overview)
2. [Directory Structure](#directory-structure)
3. [Utils Dependencies](#utils-dependencies)
4. [Prerequisites](#prerequisites)
5. [Agent Environment Setup](#agent-environment-setup)
6. [Testing the Agent](#testing-the-agent)
7. [Running the Agent](#running-the-agent)
8. [Troubleshooting](#troubleshooting)

## Overview

The MobileCybench AI Agent enables an LM agent to perform security testing of Android applications. It consists of multiple Docker containers that work together to provide:

- **Kali Container**: Security testing environment with penetration testing tools
- **Custom Agent**: AI agent that interacts with Android apps and security tools (executes tools locally via `ToolRuntime`)
- **Time Tracking**: Comprehensive timing and performance monitoring
- **Model Providers**: Flexible AI model provider architecture
- **Token Tracking**: Cost and usage monitoring for AI API calls 

### LangGraph Worker Mode
- **Static Analysis Worker**: Consumes pre-generated static reports (Semgrep, MobSFScan, QARK) from `/app/codebase/static_vuln_reports/...`, prioritizes high severity, deduplicates across tools, and produces validated findings.
- **Exploit Worker**: Builds an executable `exploit.sh` under `/app/exploit_files/` (with any supporting files in the same directory) to validate high-severity findings identified.

### LangGraph Semgrep Agent (standalone)
- `agent/langgraph/semgrep_agent.py` and `semgrep_tools.py` define a LangGraph agent that runs Semgrep live via the `run_semgrep_scan` tool and verifies findings in-code.

## Directory Structure

```
agent/
├── README.md                    
├── docker-compose.yml           # Orchestrates Kali containers
├── custom_agent.py              # Main AI agent implementation
├── agent_setup.py               # Agent environment setup and configuration
├── kali/                        # Kali Linux container configuration
│   ├── Dockerfile              # Kali container build instructions
│   └── Dockerfile.kali         # Alternative Kali container setup
├── tools/                      
│   ├── runtime.py              # Local ToolRuntime implementation
├── model_providers/            # AI model provider implementations
│   ├── __init__.py
│   ├── base.py                 # Base provider interface
│   ├── factory.py              # Provider factory pattern
│   ├── openai_provider.py      # OpenAI API provider
│   ├── gemini_provider.py      # Google Gemini provider
│   └── claude_provider.py      # Anthropic Claude provider
├── prompts/                    # AI agent prompt templates
│   ├── __init__.py
│   └── prompts.py              # Prompt definitions and templates
└── tools/                      # Static analysis helper scripts (run outside container)
    ├── run_semgrep_scan.py     # writes static_vuln_reports/semgrep/report.json
    ├── run_mobsfscan.py        # writes static_vuln_reports/mobsfscan/report.json
    └── generate_qark_report.py # writes static_vuln_reports/qark/report.json
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

- **`utils.runtime_tools`**: Runtime tool definitions

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
- **Android SDK** and emulator setup (handled by main project)

## Static Analysis Reports (Semgrep, MobSFScan, QARK)

Install tools from `requirements.txt` (includes Semgrep, MobSFScan, QARK) and generate reports from the project root. These scans can take several minutes on large APKs/codebases:
```bash
# Semgrep (writes static_vuln_reports/semgrep/report.json)
python tools/run_semgrep_scan.py <app_name> --source-dir apps/<app_name>/codebase

# MobSFScan (writes static_vuln_reports/mobsfscan/report.json)
python tools/run_mobsfscan.py <app_name> --source-dir apps/<app_name>/codebase

# QARK (writes static_vuln_reports/qark/report.json)
python tools/generate_qark_report.py <app_name> --apk apps/<app_name>/apk/<app_name>.apk
```

**Note:** The heavy static-analysis dependencies (Semgrep, MobSFScan, QARK) are commented out in `requirements.txt` to keep CI lean. Uncomment them locally before running the scan scripts above.

## Agent Environment Setup

### 1. Python Environment Setup

Make sure you're on Python 3.12 or lower for dependency compatibility.

Set up the Python virtual environment and install dependencies:

```bash
# From the project root directory (mobilecybench/)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. API Key Configuration

Create the environment file for your OpenAI API key:

```bash
# From the project root directory
echo "OPENAI_API_KEY=your_actual_api_key_here" > agent/.env
```

Or set it as an environment variable:
```bash
export OPENAI_API_KEY="sk-your-actual-openai-api-key-here"
```

### 3. Start Agent Containers

Start the agent Docker containers:

```bash
# From the project root directory
cd agent/
docker-compose up --build -d
```

This will start:
- **kali-container**: Kali Linux environment for security tools

### 4. Verify Container Status

Check that all containers are running:

```bash
docker ps
```

You should see:
- `kali-container`
- `mobilecybench-backend` (from main project)

## Testing the Agent

### 1. Interactive Shell (Dry Run)

You can run the agent in an interactive shell mode (dry run) to manually test tools without invoking the LLM:

```bash
# From the project root directory
source .venv/bin/activate
python runner.py apps/<app_name> --dry-run
```

This will launch a shell where you can execute commands like `ls`, `whoami`, etc., which are run inside the Kali container.

### 2. Basic Tool Test

You can write a simple script to import `ToolRuntime` and execute commands programmatically to verify the local execution environment working correctly.

## Running the Agent

### Full Pipeline Mode

For complete automated testing with the runner:

```bash
# Start the Kali container from Step 3.
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

**Container Connection Issues:**
- Verify Docker containers are running: `docker ps`
- Check Kali container logs: `docker logs kali-container`
- **If container not found**: Run `docker-compose up --build -d` from the agent directory

**Agent Performance Issues:**
- Check timing logs for slow LLM calls
- Review JSON timing reports for performance bottlenecks
- Monitor token usage for cost optimization
