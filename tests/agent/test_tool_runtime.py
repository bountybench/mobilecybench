"""Behavior-first tests for ToolRuntime tool filtering."""

from agent.tools.runtime import ToolRuntime

ALL_TOOLS = {
    "execute_command",
    "get_current_ui_state",
    "execute_command_with_ui_state",
}


def _exposed_names(runtime: ToolRuntime) -> set[str]:
    return {tool["name"] for tool in runtime.get_tool_definitions()}


def test_default_exposes_all_tools():
    assert _exposed_names(ToolRuntime()) == ALL_TOOLS


def test_allowed_tools_none_exposes_all_tools():
    """Explicit None matches the default behavior."""
    assert _exposed_names(ToolRuntime(allowed_tools=None)) == ALL_TOOLS


def test_allowed_tools_filters_to_listed_subset():
    runtime = ToolRuntime(allowed_tools=["execute_command"])
    assert _exposed_names(runtime) == {"execute_command"}


def test_allowed_tools_empty_list_exposes_no_tools():
    """An empty whitelist registers no tools — distinct from `None`."""
    assert _exposed_names(ToolRuntime(allowed_tools=[])) == set()


def test_unknown_tool_in_allowed_tools_is_ignored():
    """RunnerConfig validates the names; runtime tolerates unknowns to
    keep the filter logic dumb and forward-compatible."""
    runtime = ToolRuntime(allowed_tools=["execute_command", "ghost_tool"])
    assert _exposed_names(runtime) == {"execute_command"}


def test_filtered_tool_is_not_executable():
    runtime = ToolRuntime(allowed_tools=["execute_command"])
    result = runtime.execute("get_current_ui_state", {})
    assert isinstance(result, str) and "not found" in result
