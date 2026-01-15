from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Union

import google.generativeai as genai
from google.generativeai.types import GenerateContentResponse

try:
    from google.genai import types as genai_types

    HAS_GENAI_TYPES = True
except ImportError:
    HAS_GENAI_TYPES = False
    genai_types = None  # type: ignore

from agent.tools.runtime import ToolRuntime
from utils.logger import agent_logger

from .base import ModelProvider


class GeminiConversationsAPI:
    """Mock Conversations API for Gemini to maintain compatibility with OpenAI interface."""

    def __init__(self):
        self._conversations = {}
        self._items = GeminiConversationItems(self._conversations)

    def create(self, metadata=None, items=None):
        """Create a new conversation."""
        import uuid

        conv_id = str(uuid.uuid4())

        # Convert items to proper format if provided
        formatted_items = []
        if items:
            for item in items:
                if isinstance(item, dict):
                    formatted_items.append(item)

        self._conversations[conv_id] = {
            "id": conv_id,
            "metadata": metadata or {},
            "items": formatted_items,
        }
        return type("Conversation", (), {"id": conv_id})()

    def delete(self, conversation_id):
        """Delete a conversation."""
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]

    @property
    def items(self):
        """Access to conversation items."""
        return self._items


class GeminiConversationItems:
    """Mock Conversation Items API for Gemini."""

    def __init__(self, conversations):
        self._conversations = conversations

    def create(self, conversation_id, input=None):
        """Create a conversation item (e.g., add screenshot)."""
        if conversation_id in self._conversations:
            item_id = f"item-{len(self._conversations[conversation_id]['items'])}"
            item = {"id": item_id, "input": input}
            self._conversations[conversation_id]["items"].append(item)
            return type(
                "Response", (), {"items": [type("Item", (), {"id": item_id})()]}
            )()
        return None

    def delete(self, conversation_id, item_id):
        """Delete a conversation item."""
        if conversation_id in self._conversations:
            self._conversations[conversation_id]["items"] = [
                item
                for item in self._conversations[conversation_id]["items"]
                if item.get("id") != item_id
            ]


class GeminiClient:
    """Mock client object for Gemini to maintain OpenAI interface compatibility."""

    def __init__(self):
        self.conversations = GeminiConversationsAPI()


class GeminiProvider(ModelProvider):
    """Google Gemini API provider.

    Wraps client setup, env validation, and Gemini API calls.
    """

    def __init__(self, max_tool_rounds_per_turn: int = 1) -> None:
        # Configuration is done lazily to avoid issues if validation fails
        self._configured: bool = False
        self._validated: bool = False
        self._mock_client = GeminiClient()
        self._gemini_call_id = 0  # Counter for unique Gemini response IDs
        self._max_tool_rounds = (
            max_tool_rounds_per_turn  # Allow multiple tool calls per turn
        )
        self._runtime = ToolRuntime()
        self._chat_sessions: Dict[str, Any] = (
            {}
        )  # Cache ChatSession objects by conversation_id

    @property
    def client(self):
        """Return the mock client for OpenAI compatibility."""
        return self._mock_client

    def _configure_if_needed(self) -> None:
        """Configure the Gemini API with the API key."""
        if not self._configured:
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key:
                genai.configure(api_key=api_key)
                self._configured = True

    def _test_api_key_connectivity(self) -> None:
        """Attempt a minimal API call to verify the key works."""
        self._configure_if_needed()
        # List models to test connectivity
        models = genai.list_models()
        list(models)  # Force evaluation

    def validate(self) -> None:
        """Validate that GEMINI_API_KEY is set and works."""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key or not api_key.strip():
            raise ValueError(
                "GEMINI_API_KEY environment variable is required but not set. "
                "Please ensure your .env file contains GEMINI_API_KEY=your-actual-key-here "
                "or set the environment variable directly."
            )
        try:
            self._test_api_key_connectivity()
            self._validated = True
            agent_logger.info("Gemini API key validated successfully")
        except Exception as e:
            raise ValueError(
                f"Failed to validate Gemini API key: {e}. Please ensure your API key is valid."
            )

    def call(
        self,
        *,
        model: str,
        input_messages: Optional[Union[str, list]] = None,
        conversation_id: Optional[str] = None,
        tools: Optional[list] = None,
        max_output_tokens: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Call the Gemini API.

        Args:
            model: Gemini model name (e.g., 'gemini-3-pro-preview')
            input_messages: String or list of message dicts
            conversation_id: Not used for Gemini (conversations managed externally)
            tools: tools configuration (converted to Gemini function calling format)
            max_output_tokens: Maximum tokens in response
            timeout_ms: Request timeout (unused, not directly supported by Gemini SDK)
            extra: Provider-specific parameters (unused)

        Returns:
            GenerateContentResponse object with structure compatible with OpenAI responses
        """
        if not self._validated:
            raise RuntimeError(
                "Gemini provider not validated. Call validate() before making API calls."
            )

        self._configure_if_needed()

        # Extract user message from input
        user_message = None
        if input_messages is not None:
            if isinstance(input_messages, str):
                user_message = input_messages
            elif isinstance(input_messages, list):
                # Extract text from message format
                prompt_parts = []
                for msg in input_messages:
                    if isinstance(msg, dict):
                        if "content" in msg:
                            content = msg["content"]
                            if isinstance(content, list):
                                for part in content:
                                    if isinstance(part, dict) and "text" in part:
                                        prompt_parts.append(part["text"])
                            elif isinstance(content, str):
                                prompt_parts.append(content)
                        elif "text" in msg:
                            prompt_parts.append(msg["text"])

                if prompt_parts:
                    user_message = "\n".join(prompt_parts)
            else:
                raise ValueError("input_messages must be a string or list")

        # If no message, use continuation prompt
        if not user_message:
            user_message = "Continue"

        # Reasoning effort support using thinkingLevel/thinkingBudget
        thinking_config = None
        if reasoning_effort and HAS_GENAI_TYPES:
            assert genai_types is not None  # Type guard for type checker
            # Determine model version
            model_lower = model.lower()

            if "gemini-3" in model_lower:
                # Gemini 3 Pro: use thinkingLevel
                level = None
                if reasoning_effort.lower() in ("low",):
                    level = "low"
                elif reasoning_effort.lower() in ("high", "medium"):
                    level = "high"
                # else: let Gemini use default (dynamic)
                if level:
                    thinking_config = genai_types.ThinkingConfig(thinking_level=level)

        # Debug log for test verification
        agent_logger.info(
            f"[GeminiProvider] model={model} reasoning_effort={reasoning_effort} thinking_config={thinking_config}"
        )
        # Create generation config
        generation_config: Dict[str, Any] = {}
        if max_output_tokens:
            generation_config["max_output_tokens"] = max_output_tokens
        if thinking_config and HAS_GENAI_TYPES:
            assert genai_types is not None  # Type guard for type checker
            generation_config = genai_types.GenerateContentConfig(
                **generation_config, thinking_config=thinking_config
            )

        # Convert tools to Gemini function declarations
        gemini_tools = None
        if tools and len(tools) > 0:
            gemini_tools = self._convert_tools_to_gemini(tools)

        # Get or create chat session
        chat_session = None
        if conversation_id and conversation_id in self._chat_sessions:
            # Reuse existing chat session
            chat_session = self._chat_sessions[conversation_id]
            agent_logger.debug(
                f"Reusing chat session for conversation {conversation_id} (history length: {len(chat_session.history)})"
            )
        else:
            # Create new model and chat session
            if gemini_tools:
                gemini_model = genai.GenerativeModel(
                    model,
                    tools=gemini_tools,
                )
            else:
                agent_logger.warning("WARNING: No tools provided to model")
                gemini_model = genai.GenerativeModel(model)

            chat_session = gemini_model.start_chat(history=[])

            # Cache the chat session if we have a conversation_id
            if conversation_id:
                self._chat_sessions[conversation_id] = chat_session
                agent_logger.debug(
                    f"Created new chat session for conversation {conversation_id}"
                )

        # Add tool reminder to user message if tools are available
        if gemini_tools and user_message:
            user_message = f"{user_message}\n\nRecall that you have access to the following tools: {gemini_tools}. You must end every turn with a tool call."

        agent_logger.info(
            f"Gemini API request: model={model}, chat_history_len={len(chat_session.history)}, tools={len(gemini_tools) if gemini_tools else 0}"
        )

        try:
            # Increment call ID for unique tracking
            self._gemini_call_id += 1
            current_call_id = f"gemini-{self._gemini_call_id}"

            # Send message using chat session (history is automatically maintained)
            response = chat_session.send_message(
                user_message,
                generation_config=generation_config,
            )

            # Handle function calls if present
            # Allow multiple rounds for autonomous chain-of-execution
            # Can be configured via max_tool_rounds_per_turn parameter
            tool_round = 0
            tool_calls_made = []
            intermediate_reasoning = []  # Collect all text generated during tool rounds

            while tool_round < self._max_tool_rounds:
                # Check if response contains function calls
                has_function_call = False
                if hasattr(response, "candidates") and len(response.candidates) > 0:
                    candidate = response.candidates[0]
                    if hasattr(candidate, "content") and hasattr(
                        candidate.content, "parts"
                    ):
                        for part in candidate.content.parts:
                            if hasattr(part, "function_call") and part.function_call:
                                has_function_call = True
                                break

                if not has_function_call:
                    # No more function calls, break out of loop
                    break

                tool_round += 1
                agent_logger.info(
                    f"Tool calling round {tool_round}/{self._max_tool_rounds}"
                )

                # Log any text/thinking from Gemini before executing tools
                candidate = response.candidates[0]
                intermediate_text_parts = []
                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        intermediate_text_parts.append(part.text)

                if intermediate_text_parts:
                    intermediate_text = "".join(intermediate_text_parts)
                    agent_logger.info(
                        f"[GEMINI THINKING BEFORE TOOLS - {len(intermediate_text)} chars]"
                    )
                    agent_logger.info(intermediate_text)
                    agent_logger.info("-" * 40)
                    # Save intermediate reasoning for conversation history
                    intermediate_reasoning.append(intermediate_text)

                # Execute function calls and collect results
                function_responses = []
                for part in candidate.content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        fc = part.function_call
                        function_name = fc.name
                        function_args = dict(fc.args) if hasattr(fc, "args") else {}

                        agent_logger.info(f"Executing function: {function_name}")
                        agent_logger.info(
                            f"Function arguments: {json.dumps(function_args)}"
                        )

                        # Execute via Runtime
                        tool_result = self._runtime.execute(
                            function_name, function_args
                        )

                        # Track full tool result for final response
                        tool_calls_made.append(
                            {
                                "name": function_name,
                                "arguments": function_args,
                                "output": tool_result,
                            }
                        )

                        # Extract simplified result for Gemini
                        gemini_result = {}
                        if isinstance(tool_result, dict):
                            # Prefer structuredContent.result - it's already clean
                            if "structuredContent" in tool_result:
                                gemini_result = tool_result["structuredContent"]
                            # Fallback: extract text from content array
                            elif "content" in tool_result and isinstance(
                                tool_result["content"], list
                            ):
                                if len(tool_result["content"]) > 0:
                                    first_item = tool_result["content"][0]
                                    if (
                                        isinstance(first_item, dict)
                                        and "text" in first_item
                                    ):
                                        gemini_result = {"result": first_item["text"]}
                                    else:
                                        gemini_result = {"result": str(first_item)}
                            # Last resort: stringify the whole result
                            else:
                                gemini_result = {"result": json.dumps(tool_result)}
                        else:
                            gemini_result = {"result": str(tool_result)}

                        agent_logger.debug(
                            f"Simplified response for Gemini: {json.dumps(gemini_result)[:200]}..."
                        )

                        # Add function response for next Gemini call
                        function_responses.append(
                            {
                                "function_call": fc,
                                "function_response": {
                                    "name": function_name,
                                    "response": gemini_result,
                                },
                            }
                        )

                # Build function response parts for chat session
                function_response_parts = []
                for fr in function_responses:
                    # Add function response as a part using protos
                    function_response_part = genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=fr["function_response"]["name"],
                            response=fr["function_response"]["response"],
                        )
                    )
                    function_response_parts.append(function_response_part)

                # Send function responses back to chat session
                # ChatSession automatically handles function call/response conversation flow
                response = chat_session.send_message(
                    function_response_parts,
                    generation_config=generation_config,
                )

            # If we hit max_tool_rounds and the response still has no text,
            # force Gemini to provide analysis by adding a continuation prompt
            if tool_round >= self._max_tool_rounds:
                if hasattr(response, "candidates") and len(response.candidates) > 0:
                    candidate = response.candidates[0]
                    text_parts = []
                    if hasattr(candidate, "content") and hasattr(
                        candidate.content, "parts"
                    ):
                        for part in candidate.content.parts:
                            if hasattr(part, "text") and part.text:
                                text_parts.append(part.text)

                    # If no text was generated, prompt for analysis
                    if not text_parts:
                        agent_logger.info(
                            "No text generated after max tool rounds - prompting for analysis"
                        )
                        response = chat_session.send_message(
                            "Based on the tool execution results above, please provide your analysis in the required format (Reflection, Plan and Status, Thought, Log, Command).",
                            generation_config=generation_config,
                        )

            # Log summary if multiple tool rounds were used
            if tool_round > 0:
                agent_logger.info(
                    f"Completed {tool_round} tool calling round(s) with {len(tool_calls_made)} total tool call(s)"
                )

            # Convert Gemini response to OpenAI-compatible format
            converted_response = self._convert_response(
                response, request_id=current_call_id
            )

            # Add tool call information to output
            if tool_calls_made:
                output_items = list(getattr(converted_response, "output", []))
                for tool_call in tool_calls_made:
                    output_items.append(
                        type(
                            "ToolCallItem",
                            (),
                            {
                                "type": "tool_call",
                                "name": tool_call["name"],
                                "arguments": json.dumps(tool_call["arguments"]),
                                "output": json.dumps(tool_call["output"]),
                                "error": None,
                            },
                        )()
                    )
                # Update output attribute
                converted_response.output = output_items

            return converted_response

        except Exception as e:
            agent_logger.error(f"Gemini API call failed: {e}")
            raise

    def _convert_json_schema_to_gemini(
        self, json_schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Convert JSON schema to Gemini parameter format.

        Args:
            json_schema: Tool input schema (JSON Schema format)

        Returns:
            Gemini-compatible parameter schema
        """
        # Gemini uses type_ field with uppercase enum values
        # Map JSON Schema types to Gemini Type enum
        type_mapping = {
            "object": "OBJECT",
            "string": "STRING",
            "number": "NUMBER",
            "integer": "INTEGER",
            "boolean": "BOOLEAN",
            "array": "ARRAY",
        }

        schema_type = json_schema.get("type", "object").lower()
        gemini_type = type_mapping.get(schema_type, "OBJECT")

        gemini_schema: Dict[str, Any] = {
            "type_": gemini_type,
        }

        # Add description if present
        if "description" in json_schema:
            gemini_schema["description"] = json_schema["description"]

        # Convert properties recursively if present
        if "properties" in json_schema:
            gemini_properties: Dict[str, Any] = {}
            for prop_name, prop_schema in json_schema["properties"].items():
                # Recursively convert nested schemas
                if isinstance(prop_schema, dict):
                    gemini_properties[prop_name] = self._convert_json_schema_to_gemini(
                        prop_schema
                    )
                else:
                    gemini_properties[prop_name] = {
                        "type_": "STRING"
                    }  # Default fallback
            gemini_schema["properties"] = gemini_properties

        if "required" in json_schema:
            gemini_schema["required"] = json_schema["required"]

        # Handle array items
        if "items" in json_schema and isinstance(json_schema["items"], dict):
            gemini_schema["items"] = self._convert_json_schema_to_gemini(
                json_schema["items"]
            )

        return gemini_schema

    def _convert_tools_to_gemini(self, tools: list) -> Optional[list]:
        """Convert OpenAI-style tool definitions to Gemini function declarations.

        Args:
            tools: List containing tool definitions

        Returns:
            List of Gemini function declarations or None
        """
        if not tools:
            return None

        # Check if it's already in Gemini format (list of FunctionDeclaration)
        # or if it's our ToolRuntime format (OpenAI style)

        gemini_functions = []
        for tool in tools:
            # Handle OpenAI format: {"type": "function", "function": {"name": ..., "parameters": ...}}
            if isinstance(tool, dict) and "function" in tool:
                func_def = tool["function"]
                function_decl = {
                    "name": func_def.get("name", ""),
                    "description": func_def.get("description", ""),
                }

                if "parameters" in func_def:
                    function_decl["parameters"] = self._convert_json_schema_to_gemini(
                        func_def["parameters"]
                    )
                else:
                    function_decl["parameters"] = {"type": "object", "properties": {}}

                gemini_functions.append(function_decl)

            # Handle dict but not wrapped in "function" (direct definition)
            elif isinstance(tool, dict) and "name" in tool and "parameters" in tool:
                function_decl = {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": self._convert_json_schema_to_gemini(
                        tool["parameters"]
                    ),
                }
                gemini_functions.append(function_decl)

        if not gemini_functions:
            return None

        return gemini_functions

    def _convert_response(
        self, response: GenerateContentResponse, request_id: str = "gemini-response"
    ) -> Any:
        """Convert Gemini response to OpenAI Responses API compatible format.

        Args:
            response: Gemini GenerateContentResponse
            request_id: Unique identifier for this request

        Returns:
            Dict with OpenAI-compatible structure
        """
        # Extract text from response
        text = ""

        try:
            # Check if response has candidates
            if hasattr(response, "candidates") and len(response.candidates) > 0:
                candidate = response.candidates[0]
                if hasattr(candidate, "content") and hasattr(
                    candidate.content, "parts"
                ):
                    # Extract text parts (function calls are handled in call() method)
                    text_parts = []
                    has_function_call = False
                    for part in candidate.content.parts:
                        if hasattr(part, "text") and part.text:
                            text_parts.append(part.text)
                        elif hasattr(part, "function_call") and part.function_call:
                            has_function_call = True

                    text = "".join(text_parts)

                    # If no text extracted but there's a function call, that's expected
                    # Don't try to access response.text (it will error)
                    if not text and not has_function_call:
                        # Only try response.text if there's no function call
                        try:
                            text = (
                                response.text
                                if hasattr(response, "text") and response.text
                                else ""
                            )
                        except Exception:
                            # response.text can fail for various reasons, just leave text empty
                            pass

        except Exception as e:
            agent_logger.error(f"Error extracting response content: {e}")
            text = ""

        # Extract token counts from Gemini's usage_metadata
        input_tokens = (
            response.usage_metadata.prompt_token_count
            if hasattr(response, "usage_metadata")
            else 0
        )
        output_tokens = (
            response.usage_metadata.candidates_token_count
            if hasattr(response, "usage_metadata")
            else 0
        )
        total_tokens = (
            response.usage_metadata.total_token_count
            if hasattr(response, "usage_metadata")
            else 0
        )
        cached_tokens = (
            response.usage_metadata.cached_content_token_count
            if hasattr(response, "usage_metadata")
            and hasattr(response.usage_metadata, "cached_content_token_count")
            else 0
        )

        # Build OpenAI-compatible response structure
        # Note: usage must be an object with attributes (not a dict) for token tracker compatibility
        return type(
            "GeminiResponse",
            (),
            {
                "id": f"gemini-response-{request_id}",
                "output_text": text,
                "items": [
                    type(
                        "Item",
                        (),
                        {
                            "role": "assistant",
                            "content": [{"type": "text", "text": text}] if text else [],
                            "usage": type(
                                "Usage",
                                (),
                                {
                                    "input_tokens": input_tokens,
                                    "output_tokens": output_tokens,
                                    "cached_tokens": cached_tokens,
                                },
                            )(),
                        },
                    )()
                ],
                "usage": type(
                    "Usage",
                    (),
                    {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": total_tokens,
                        "cached_tokens": cached_tokens,
                    },
                )(),
                "tool_outputs": [],
                "output": [],
            },
        )()
