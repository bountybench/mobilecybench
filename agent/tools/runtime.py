import json
from typing import Any, Callable, Dict, Tuple, Union

from pydantic import BaseModel, ValidationError

from agent.backend.docker_ops import execute_command_internal, get_ui_state
from agent.tools.schemas import ExecuteCommand, ExecuteCommandWithUI, GetUIState
from utils.logger import logger


class ToolRuntime:
    """
    Runtime environment for executing tools locally.
    Handles argument parsing, validation, and execution.
    """

    def __init__(self):
        # Map tool names to (Schema, Function)
        self.registry: Dict[str, Tuple[type[BaseModel], Callable]] = {
            "execute_command": (ExecuteCommand, self._execute_command),
            "get_current_ui_state": (GetUIState, self._get_current_ui_state),
            "execute_command_with_ui_state": (
                ExecuteCommandWithUI,
                self._execute_command_with_ui_state,
            ),
        }

    def _execute_command(self, args: ExecuteCommand) -> str:
        try:
            return execute_command_internal(args.command)
        except Exception as e:
            return f"Error: {str(e)}"

    def _get_current_ui_state(self, args: GetUIState) -> dict:
        try:
            return get_ui_state()
        except Exception as e:
            return {"error": f"Failed to get UI state: {str(e)}", "ui_elements": []}

    def _execute_command_with_ui_state(self, args: ExecuteCommandWithUI) -> dict:
        try:
            command_output = execute_command_internal(args.command)
            ui_data = get_ui_state()
            ui_data["result"] = command_output
            return ui_data
        except Exception as e:
            ui_data = get_ui_state()
            ui_data["result"] = f"Error: {str(e)}"
            return ui_data

    def _parse_arguments(
        self, schema: type[BaseModel], args: Union[str, Dict[str, Any]]
    ) -> BaseModel:
        """
        Parses arguments from a JSON string or dictionary into a validated Pydantic model.
        """
        if isinstance(args, str):
            try:
                parsed_args = json.loads(args)
            except json.JSONDecodeError:
                # If it's a string but not JSON, we might need to handle it differently
                # But for now, assume all string args are JSON encoded
                raise ValueError(f"Arguments must be valid JSON: {args}")
        elif isinstance(args, dict):
            parsed_args = args
        else:
            raise ValueError(f"Unsupported argument type: {type(args)}")

        return schema(**parsed_args)

    def execute(self, tool_name: str, tool_args: Union[str, Dict[str, Any]]) -> Any:
        """
        Execute a tool by name with the provided arguments.

        Args:
            tool_name: The name of the tool to execute.
            tool_args: The arguments for the tool (JSON string or dict).

        Returns:
            The result of the tool execution.
        """
        if tool_name not in self.registry:
            return f"Error: Tool '{tool_name}' not found."

        schema, func = self.registry[tool_name]

        try:
            # Parse and validate arguments
            validated_args = self._parse_arguments(schema, tool_args)

            # Execute the function
            return func(validated_args)

        except ValidationError as e:
            return f"Error: Invalid arguments for tool '{tool_name}': {e}"
        except ValueError as e:
            return f"Error: {str(e)}"
        except Exception as e:
            logger.error(f"Unexpected error executing tool {tool_name}: {e}")
            return f"Error: Unexpected error: {str(e)}"

    def get_tool_definitions(self) -> list:
        """
        Generates tool definitions in the format expected by the model provider (OpenAI compatible).
        """
        tools = []
        for name, (schema_cls, _) in self.registry.items():
            schema = schema_cls.model_json_schema()

            # Extract description from docstring or schema title
            description = schema.get("description", f"Tool {name}")

            # Clean up schema for OpenAI compatibility
            if "title" in schema:
                del schema["title"]
            if "description" in schema:
                del schema["description"]

            tool_def = {
                "type": "function",
                "name": name,
                "description": description,
                "parameters": schema,
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": schema,
                },
            }
            tools.append(tool_def)
        return tools
