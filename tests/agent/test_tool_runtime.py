"""Behavior-first tests for ToolRuntime."""

from agent.custom.tools.runtime import ToolRuntime

ALL_TOOLS = {
    "execute_command",
    "get_current_ui_state",
    "execute_command_with_ui_state",
}


def _exposed_names(runtime: ToolRuntime) -> set[str]:
    return {tool["name"] for tool in runtime.get_tool_definitions()}


def test_exposes_full_tool_set():
    """All three tools are registered; no filtering surface remains."""
    assert _exposed_names(ToolRuntime()) == ALL_TOOLS
