"""
Hierarchical Agent System - Supervisor and Worker Architecture

This package implements a hierarchical multi-agent system for cybersecurity
vulnerability analysis and exploitation:

- **Supervisor Agent**: Coordinates worker agents and manages the overall workflow
- **Static Analysis Worker**: Analyzes Semgrep results to identify HIGH SEVERITY vulnerabilities
- **Exploit Worker**: Creates executable exploit.sh scripts to validate vulnerabilities

All workers use MCP tools from runner_config.json for command execution and
file operations, ensuring consistency and proper tool management.

Architecture:
    Supervisor
    ├── Static Analysis Worker (reads semgrep_results.json, analyzes vulnerabilities)
    └── Exploit Worker (creates exploit.sh to validate findings)

Usage:
    from agent.hierarchical_agent import create_and_run_supervisor_system

    result = create_and_run_supervisor_system(
        model="gpt-5.1-2025-11-13",
        max_iterations=30,
        allowed_tools=["execute_command", "get_current_ui_state"],
        user_input="Analyze the codebase for vulnerabilities"
    )
"""

from agent.hierarchical_agent.exploit_worker import (
    EXPLOIT_TOOLS,
    EXPLOIT_WORKER_SYSTEM_PROMPT,
    create_exploit_worker_prompt,
)
from agent.hierarchical_agent.static_analysis_worker import (
    STATIC_ANALYSIS_SYSTEM_PROMPT,
    create_static_analysis_worker_prompt,
)
from agent.hierarchical_agent.supervisor_agent import (
    DEFAULT_SUPERVISOR_PROMPT,
    HierarchicalAgentSystem,
    WorkerAgent,
    create_and_run_supervisor_system,
)

__all__ = [
    # Supervisor components
    "HierarchicalAgentSystem",
    "WorkerAgent",
    "create_and_run_supervisor_system",
    "DEFAULT_SUPERVISOR_PROMPT",
    # Static analysis worker components
    "STATIC_ANALYSIS_SYSTEM_PROMPT",
    "create_static_analysis_worker_prompt",
    # Exploit worker components
    "EXPLOIT_WORKER_SYSTEM_PROMPT",
    "EXPLOIT_TOOLS",
    "create_exploit_worker_prompt",
]
