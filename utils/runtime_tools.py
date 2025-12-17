"""
Tool Wrappers for LangChain Agents

This module provides LangChain-compatible tool wrappers for local tool runtime.
These tools enable agents to execute commands and interact with the Android
emulator environment.

The tools wrap ToolRuntime to provide a clean interface for LangChain agents.
"""

from typing import List, Optional

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from agent.tools.runtime import ToolRuntime
from utils.logger import agent_logger

# Global runtime instance
_runtime_instance = None


def _get_runtime() -> ToolRuntime:
    """Get or create the shared ToolRuntime instance."""
    global _runtime_instance
    if _runtime_instance is None:
        _runtime_instance = ToolRuntime()
    return _runtime_instance


class ExecuteCommandInput(BaseModel):
    """Input schema for execute_command tool."""

    command: str = Field(
        description="Bash command to execute in the Kali Linux environment"
    )


class UIStateInput(BaseModel):
    """Input schema for get_current_ui_state tool (no parameters needed)."""

    pass


class ExecuteCommandWithUIInput(BaseModel):
    """Input schema for execute_command_with_ui_state tool."""

    command: str = Field(
        description="Bash command to execute along with UI state capture"
    )


@tool(args_schema=ExecuteCommandInput)
def execute_command(command: str) -> str:
    """
    Execute a bash command in the Kali Linux environment.

    This tool allows you to run shell commands, manipulate files, analyze code,
    and perform security testing operations in the containerized Kali environment.

    Args:
        command: The bash command to execute

    Returns:
        The command output or error message

    Examples:
        - "ls -la /app/codebase"
        - "cat /app/codebase/static_vuln_reports/semgrep/report.json"
        - "grep -r 'vulnerable_function' /app/codebase"
    """
    try:
        agent_logger.debug(f"Executing command via ToolRuntime: {command}")
        runtime = _get_runtime()
        # ToolRuntime.execute takes name and args(dict or str)
        result = runtime.execute("execute_command", {"command": command})

        # result is directly the string output for execute_command
        agent_logger.debug("Command succeeded/executed")
        return result

    except Exception as e:
        error_msg = f"Error executing command: {str(e)}"
        agent_logger.error(error_msg)
        return error_msg


@tool(args_schema=UIStateInput)
def get_current_ui_state() -> str:
    """
    Get the current UI state of the Android emulator.

    This tool captures the current screen state of the Android emulator,
    including UI hierarchy and element information. Useful for understanding
    the current state of the app during testing.

    Returns:
        JSON string containing the UI state information
    """
    try:
        agent_logger.debug("Getting current UI state via Runtime")
        runtime = _get_runtime()
        result = runtime.execute("get_current_ui_state", {})

        # result is a dict, we should converting to string for LangChain tool return
        import json

        return json.dumps(result, indent=2)

    except Exception as e:
        error_msg = f"Error getting UI state: {str(e)}"
        agent_logger.error(error_msg)
        return error_msg


@tool(args_schema=ExecuteCommandWithUIInput)
def execute_command_with_ui_state(command: str) -> str:
    """
    Execute a bash command and capture the current UI state.

    This tool combines command execution with UI state capture, useful for
    testing how commands affect the Android app's UI.

    Args:
        command: The bash command to execute

    Returns:
        Combined output including command result and UI state
    """
    try:
        agent_logger.debug(f"Executing command with UI state: {command}")
        runtime = _get_runtime()
        result = runtime.execute("execute_command_with_ui_state", {"command": command})

        # result is a dict
        import json

        return json.dumps(result, indent=2)

    except Exception as e:
        error_msg = f"Error executing command with UI state: {str(e)}"
        agent_logger.error(error_msg)
        return error_msg


def create_runtime_tools(
    allowed_tools: Optional[List[str]] = None, ngrok_base_url: Optional[str] = None
) -> List[BaseTool]:
    """
    Factory function to create tool objects for LangChain agents.

    This function creates and returns a list of LangChain-compatible tool objects
    that wrap the functionality. Tools can be filtered using the
    allowed_tools parameter.

    Args:
        allowed_tools: Optional list of tool names to include. If None, all tools are included.
                      Valid tool names: "execute_command", "get_current_ui_state",
                      "execute_command_with_ui_state"
        ngrok_base_url: Optional (unused in local runtime but kept for compatibility).

    Returns:
        List of BaseTool objects ready to be used with LangChain agents

    Example:
        >>> tools = create_runtime_tools(allowed_tools=["execute_command", "get_current_ui_state"])
        >>> agent = create_agent(model=llm, tools=tools, system_prompt=prompt)
    """
    # All available tools
    all_tools = [
        execute_command,
        get_current_ui_state,
        execute_command_with_ui_state,
    ]

    # Filter by allowed_tools if specified
    if allowed_tools is not None:
        filtered_tools = [t for t in all_tools if t.name in allowed_tools]
        agent_logger.info(
            f"Created {len(filtered_tools)} tools (filtered from {len(all_tools)}): "
            f"{[t.name for t in filtered_tools]}"
        )
        return filtered_tools

    agent_logger.info(f"Created {len(all_tools)} tools: {[t.name for t in all_tools]}")
    return all_tools


# Export tools for direct import
RUNTIME_TOOLS = [execute_command, get_current_ui_state, execute_command_with_ui_state]
