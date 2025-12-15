"""
Custom Agent V2 - Simple LangGraph Agent for Mobile Cybersecurity Testing.

This module provides a simple, debuggable LangGraph agent that:
- Executes commands in Kali Linux container
- Interacts with Android emulator via ADB
- Inspects UI state and captures screenshots
- Uses GPT-5.2 with reasoning mode toggle
- Serves as foundation for future hierarchical agent system

Architecture:
    Host (Python): Agent code and tools
    Kali Container: Command execution via docker exec
    Android Emulator: Connected via ADB (host.docker.internal:5037)

Usage:
    from agent.custom_agent_v2 import SimpleAgent, run_simple_agent

    # Quick test
    result = run_simple_agent("Check if emulator is running")

    # Full control
    agent = SimpleAgent(
        model="gpt-5.2",
        reasoning_effort="medium",
        enable_reasoning=True
    )
    result = agent.run("Analyze installed apps")
"""

from agent.custom_agent_v2.config import (
    AgentConfig,
    get_model_config,
    setup_langsmith,
    validate_environment,
)
from agent.custom_agent_v2.kali_tools import (
    KALI_TOOLS,
    execute_adb_command,
    execute_command,
    get_emulator_info,
    get_ui_state,
    take_screenshot,
)
from agent.custom_agent_v2.shared_knowledge import (
    CodeIndex,
    SharedKnowledgeStore,
    Symbol,
    TaintAnalysis,
    Vulnerability,
)
from agent.custom_agent_v2.simple_agent import SimpleAgent, run_simple_agent

__version__ = "2.0.0"

__all__ = [
    # Main agent
    "SimpleAgent",
    "run_simple_agent",
    # Configuration
    "AgentConfig",
    "setup_langsmith",
    "get_model_config",
    "validate_environment",
    # Tools
    "KALI_TOOLS",
    "execute_command",
    "execute_adb_command",
    "get_emulator_info",
    "get_ui_state",
    "take_screenshot",
    # Shared knowledge
    "SharedKnowledgeStore",
    "Vulnerability",
    "CodeIndex",
    "Symbol",
    "TaintAnalysis",
]
