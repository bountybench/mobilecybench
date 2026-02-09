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
│   ├── base.py                 # Base provider interface (stateful contract)
│   ├── factory.py              # Provider factory (routes by model name)
├── prompts/                    # AI agent prompt templates
│   ├── __init__.py
│   └── prompts.py              # Prompt definitions and templates
└── tools/
    ├── runtime.py              # Local ToolRuntime implementation
    └── schemas.py              # Tool schemas
```

## Execution Flow

At runtime, `runner.py` uses `agent/agent_setup.py` to start the Kali container (`kali-container`) and mount the app codebase. The agent executes tools inside that container via `ToolRuntime`.

If an exploit script is produced at `/app/exploit_files/exploit.sh`, the runner will reset the environment, execute the exploit, and re-run probes to validate impact.

## Model Providers

Providers are **stateful**: each instance owns its conversation state.
The factory (`get_model_provider`) returns a fully configured, ready-to-use
instance. The interface defined in `base.py`:

1. `call(input)` — per-turn invocation; returns a `ProviderResponse`.
2. `get_conversation_history()` — structured log for archiving.

The agent (`custom_agent.py`) is **stateless** with respect to conversation — it
passes new input each turn, reads back a normalized `ProviderResponse`, and
never touches provider-internal state.

**Routing:** `factory.py` inspects the model name and returns either
`OpenAIProvider` (for GPT/o-series models) or `LiteLLMProvider` (for
Anthropic, Gemini, and any other model supported by LiteLLM).

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
