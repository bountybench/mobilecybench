from typing import Literal, get_args

ToolName = Literal[
    "execute_command",
    "get_current_ui_state",
    "execute_command_with_ui_state",
]

TOOL_NAMES: tuple[ToolName, ...] = get_args(ToolName)
