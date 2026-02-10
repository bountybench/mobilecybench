# MobileCybench AI Agent

For setup and usage, see:
- `documentation/AGENT_SETUP.md`
- `documentation/EXPERIMENTS.md`

## Table of Contents
1. [Overview](#overview)
2. [Directory Structure](#directory-structure)
3. [Utils Dependencies](#utils-dependencies)
4. [Execution Flow](#execution-flow)

## Overview

The MobileCybench AI Agent enables an LM agent to perform security testing of Android applications. The runner spins up a Kali-based container (`kali-container`) and executes tools via `ToolRuntime`. Provider selection is handled in `agent/model_providers/factory.py` based on the configured model name.

## Directory Structure

```
agent/
├── README.md                    
├── ARCHITECTURE.md              # This document
├── custom_agent.py              # Main AI agent implementation
├── agent_setup.py               # Agent environment setup and container launch
├── kali/                        # Kali Linux container configuration
│   ├── Dockerfile              # Kali container build instructions
│   └── Dockerfile.kali         # Alternative Kali container setup
├── model_providers/            # AI model provider implementations
│   ├── __init__.py
│   ├── base.py                 # Base provider interface
│   ├── factory.py              # Provider factory pattern
│   ├── openai_provider.py      # OpenAI API provider
│   ├── gemini_provider.py      # Google Gemini provider
├── prompts/                    # AI agent prompt templates
│   ├── __init__.py
│   └── prompts.py              # Prompt definitions and templates
└── tools/
    ├── runtime.py              # Local ToolRuntime implementation
    └── schemas.py              # Tool schemas
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

## Execution Flow

At runtime, `runner.py` uses `agent/agent_setup.py` to start the Kali container (`kali-container`) and mount the app codebase. The agent executes tools inside that container via `ToolRuntime`.

If an exploit script is produced at `/app/exploit_files/exploit.sh`, the runner will reset the environment, execute the exploit, and re-run probes to validate impact.

## Agent Behavior (high level)

- Prompts live in `agent/prompts/` and define system/task framing for the agent.
- Agent type is selected with `--agent-type` (`custom` or `codex`).

## Agent Environment (what it can see and do)
- **Runtime container**: The agent runs inside the Kali container (`kali-container`). It sees the app codebase mounted under `/app/codebase`.
- **Tools**: It executes commands via `ToolRuntime` (shell commands, ADB, network tools) with the allowlist defined in the runner config.
- **Access**:
  - Emulator access via ADB (host‑forwarded into the container).
  - App servers via Docker networks (`shared_net` for accessible services).
  - No direct host filesystem access outside mounted paths.
- **Inputs**: The agent prompt includes app metadata (`metadata.json` values) and credentials (if provided).
