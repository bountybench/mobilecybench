# Multi-Agent Security Testing Architecture

This directory implements a **multi-agent parallel approach** for identifying security vulnerabilities in mobile applications, contrasting with the single-flow sequential methodology in the root-level `runner.py`.

## Overview

The multi-agent system uses a **divide-and-conquer strategy** where multiple specialized agent instances work in parallel to explore different vulnerability hypotheses, coordinated through a graph-based orchestration layer.

## Setup

### Environment Configuration

Create a `.env` file in the `agent/` directory with the following parameters:

```bash
# OpenAI API Key (required for ChatOpenAI models)
OPENAI_API_KEY=your_openai_api_key_here

# LangSmith Tracing (optional but recommended for debugging)
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=your_langsmith_api_key_here
LANGSMITH_PROJECT=your_project_name
```

**Parameter Descriptions**:
- `OPENAI_API_KEY`: Your OpenAI API key for accessing GPT models
- `LANGSMITH_TRACING`: Enable/disable LangSmith tracing for debugging LangGraph execution
- `LANGSMITH_ENDPOINT`: LangSmith API endpoint (default: `https://api.smith.langchain.com`)
- `LANGSMITH_API_KEY`: Your LangSmith API key for trace logging ([get one here](https://smith.langchain.com/))
- `LANGSMITH_PROJECT`: Project name for organizing traces in LangSmith dashboard

**Note**: LangSmith parameters are optional but highly recommended for visualizing the multi-agent execution flow and debugging worker interactions.

## Architecture

### `arch.py` - Graph Orchestration

The core orchestration layer that defines a **LangGraph-based state machine** with three main node types:

- **Summarizer Node**: Analyzes initial vulnerability reports (e.g., from Semgrep) and decomposes them into discrete, specialized investigation tasks
- **Worker Nodes**: Multiple parallel agent instances that independently investigate specific vulnerabilities. Each worker:
  - Maintains its own conversation state and tool interaction history
  - Executes up to `max_turns` iterations of observation-action cycles
  - Uses MCP tools (via `mcp_connector.py`) to interact with the Android environment
  - Produces a focused final report on its assigned vulnerability hypothesis
- **Collector Node**: Aggregates results from all workers and determines whether vulnerabilities were successfully exploited

**Graph Flow**:
```
Summarizer → [Worker₁, Worker₂, ..., Workerₙ] → Collector
             (parallel execution)
```

Each worker operates as a **subgraph** with its own turn-based execution loop (`turn_node` → `mcp_tool_call` → `turn_node`), enabling parallel exploration without state interference.

The auxiliary LLM is designated as the "summarizer" node, which receives very large input and attempts to break it down into workable issues that are topically categorized to the best of the model's ability.

The later nodes, which perform the actual vulnerability-finding, reporting, and verification, draw from the reasoning LLM.

This cost structure is reasonably priced, as most of the tokens are going to be in the input to the auxiliary LLM.

## Example Usage

```python
from agent.multi.pipeline import call_pipeline
from langchain_openai import ChatOpenAI

# Run multi-agent system with initial vulnerability report and pricing tracking
result = call_pipeline(
    list_of_vuln_files=["semgrep-results.json"],
    auxiliary_llm=ChatOpenAI(model="gpt-5-nano-2025-08-07"),
    reasoning_llm=ChatOpenAI(model="gpt-5.1-2025-11-13", reasoning_effort="high"),
    config={
        "max_turns": 40,
        "initial_tree_context": get_directory_tree(),  # Codebase context
        "app_server": "http://home-assistant-server:8123",
        "network_access": True,
    },
    track_pricing=True,  # Enable token usage and cost tracking
    pricing_output_file="langgraph_pricing.json",  # Save pricing data
)

# Access pricing information
if "pricing" in result:
    print(f"Total cost: ${result['pricing']['total_cost_usd']:.6f}")
    print(f"Total calls: {result['pricing']['total_calls']}")
```

### Cost Tracking

The pipeline includes built-in **token usage and pricing tracking** via `langgraph_pricing_tracker.py`:

- **Automatic tracking**: Wraps LLMs with callbacks to capture token usage from all calls
- **Per-model breakdown**: Aggregates costs separately for auxiliary vs reasoning models
- **Per-worker metrics**: Tracks which parallel workers made which calls
- **Detailed logging**: Saves per-call records and aggregated summaries to JSON

Example pricing output (`langgraph_pricing.json`):
```json
{
  "summary": {
    "total_cost_usd": 1.234567,
    "total_calls": 45,
    "worker_count": 3,
    "by_model": {
      "gpt-5-nano": {
        "call_count": 5,
        "total_cost_usd": 0.05
      },
      "gpt-5.1": {
        "call_count": 40,
        "total_cost_usd": 1.18
      }
    },
    "by_role": {
      "auxiliary": {"call_count": 5, "total_cost_usd": 0.05},
      "reasoning": {"call_count": 40, "total_cost_usd": 1.18}
    }
  },
  "detailed_calls": [...]
}
```