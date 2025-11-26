"""
MCP Tool Wrappers for LangChain Agents

This module provides LangChain-compatible tool wrappers for MCP (Model Context Protocol)
server tools. These tools enable agents to execute commands and interact with the Android
emulator environment through the MCP server.

The tools wrap MCPToolExecutor to provide a clean interface for LangChain agents.
"""

from typing import List, Optional

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from agent.mcp.direct_tool_executor import MCPToolExecutor
from utils.logger import agent_logger

# Global executor instance to prevent creating new connections/logs for every tool call
_executor_instance = None


def _get_executor() -> MCPToolExecutor:
    """Get or create the shared MCPToolExecutor instance."""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = MCPToolExecutor()
    return _executor_instance


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
        - "cat /app/codebase/semgrep_results.json"
        - "grep -r 'vulnerable_function' /app/codebase"
    """
    try:
        agent_logger.debug(f"Executing command via MCP: {command}")
        executor = _get_executor()
        result = executor.call_tool("execute_command", command)
        success, message = executor._extract_result(result)

        if success:
            agent_logger.debug(f"Command succeeded: {command[:100]}...")
            return message
        else:
            agent_logger.warning(f"Command failed: {command[:100]}... - {message}")
            return f"Error executing command: {message}"

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
        agent_logger.debug("Getting current UI state via MCP")
        executor = _get_executor()
        result = executor.call_tool("get_current_ui_state", "")
        success, message = executor._extract_result(result)

        if success:
            agent_logger.debug("UI state retrieved successfully")
            return message
        else:
            agent_logger.warning(f"Failed to get UI state: {message}")
            return f"Error getting UI state: {message}"

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
        executor = _get_executor()
        result = executor.call_tool("execute_command_with_ui_state", command)
        success, message = executor._extract_result(result)

        if success:
            agent_logger.debug("Command with UI state succeeded")
            return message
        else:
            agent_logger.warning(f"Command with UI state failed: {message}")
            return f"Error executing command with UI state: {message}"

    except Exception as e:
        error_msg = f"Error executing command with UI state: {str(e)}"
        agent_logger.error(error_msg)
        return error_msg


def create_mcp_tools(
    allowed_tools: Optional[List[str]] = None, ngrok_base_url: Optional[str] = None
) -> List[BaseTool]:
    """
    Factory function to create MCP tool objects for LangChain agents.

    This function creates and returns a list of LangChain-compatible tool objects
    that wrap the MCP server functionality. Tools can be filtered using the
    allowed_tools parameter.

    Args:
        allowed_tools: Optional list of tool names to include. If None, all tools are included.
                      Valid tool names: "execute_command", "get_current_ui_state",
                      "execute_command_with_ui_state"
        ngrok_base_url: Optional ngrok base URL for MCP server connection.
                       If None, will auto-discover from ngrok API.

    Returns:
        List of BaseTool objects ready to be used with LangChain agents

    Example:
        >>> tools = create_mcp_tools(allowed_tools=["execute_command", "get_current_ui_state"])
        >>> agent = create_agent(model=llm, tools=tools, system_prompt=prompt)
    """
    # All available MCP tools
    all_tools = [
        execute_command,
        get_current_ui_state,
        execute_command_with_ui_state,
    ]

    # Filter by allowed_tools if specified
    if allowed_tools is not None:
        filtered_tools = [t for t in all_tools if t.name in allowed_tools]
        agent_logger.info(
            f"Created {len(filtered_tools)} MCP tools (filtered from {len(all_tools)}): "
            f"{[t.name for t in filtered_tools]}"
        )
        return filtered_tools

    agent_logger.info(
        f"Created {len(all_tools)} MCP tools: {[t.name for t in all_tools]}"
    )
    return all_tools


# Export tools for direct import
MCP_TOOLS = [execute_command, get_current_ui_state, execute_command_with_ui_state]
