"""LiteLLM provider for unified model access.

This module provides a unified interface to multiple LLM providers (OpenAI, Gemini,
Anthropic, etc.) using LiteLLM as the abstraction layer.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional, Union

import litellm
from litellm import completion

from utils.logger import agent_logger

from .base import ModelProvider


class LiteLLMConversationsAPI:
    """Mock Conversations API for LiteLLM to maintain compatibility with OpenAI interface.

    Since LiteLLM uses stateless completion calls, we manage conversation history internally.
    """

    def __init__(self, provider: "LiteLLMProvider"):
        self._provider = provider
        self._conversations: Dict[str, Dict] = {}
        self._items = LiteLLMConversationItems(self._conversations, provider)

    def create(self, metadata: Optional[Dict] = None, items: Optional[List] = None) -> Any:
        """Create a new conversation."""
        conv_id = str(uuid.uuid4())

        # Initialize conversation with message history
        messages = []
        if items:
            for item in items:
                if isinstance(item, dict):
                    role = item.get("role", "user")
                    content = item.get("content", "")
                    if isinstance(content, list):
                        # Handle content array format
                        text_parts = []
                        for part in content:
                            if isinstance(part, dict) and "text" in part:
                                text_parts.append(part["text"])
                        content = "\n".join(text_parts) if text_parts else ""
                    messages.append({"role": role, "content": content})

        self._conversations[conv_id] = {
            "id": conv_id,
            "metadata": metadata or {},
            "messages": messages,
        }
        return type("Conversation", (), {"id": conv_id})()

    def retrieve(self, conversation_id: str) -> Any:
        """Retrieve conversation data."""
        conv = self._conversations.get(conversation_id, {})
        return type(
            "Conversation",
            (),
            {
                "id": conv.get("id", conversation_id),
                "created_at": None,
                "metadata": conv.get("metadata", {}),
                "object": "conversation",
            },
        )()

    def delete(self, conversation_id: str) -> None:
        """Delete a conversation."""
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]

    @property
    def items(self) -> "LiteLLMConversationItems":
        """Access to conversation items."""
        return self._items


class LiteLLMConversationItems:
    """Mock Conversation Items API for LiteLLM."""

    def __init__(self, conversations: Dict, provider: "LiteLLMProvider"):
        self._conversations = conversations
        self._provider = provider
        self._item_counter = 0

    def create(
        self, conversation_id: str, items: Optional[List] = None, input: Optional[Any] = None
    ) -> Any:
        """Add items to a conversation."""
        if conversation_id not in self._conversations:
            return None

        created_items = []

        # Handle items list (messages)
        if items:
            for item in items:
                if isinstance(item, dict):
                    self._item_counter += 1
                    item_id = f"item-{self._item_counter}"

                    role = item.get("role", "user")
                    content = item.get("content", "")

                    # Handle content array format (for images, etc.)
                    if isinstance(content, list):
                        # For now, extract text content (images need special handling)
                        text_parts = []
                        for part in content:
                            if isinstance(part, dict):
                                if part.get("type") == "input_text" and "text" in part:
                                    text_parts.append(part["text"])
                                elif part.get("type") == "input_image":
                                    # Store image data for multimodal models
                                    text_parts.append("[Image attached]")
                        content = "\n".join(text_parts) if text_parts else str(content)

                    msg = {"role": role, "content": content, "id": item_id}
                    self._conversations[conversation_id]["messages"].append(msg)
                    created_items.append(type("Item", (), {"id": item_id})())

        # Handle single input (legacy format)
        if input is not None:
            self._item_counter += 1
            item_id = f"item-{self._item_counter}"
            msg = {"role": "user", "content": str(input), "id": item_id}
            self._conversations[conversation_id]["messages"].append(msg)
            created_items.append(type("Item", (), {"id": item_id})())

        return type("Response", (), {"items": created_items})()

    def list(
        self,
        conversation_id: str,
        limit: int = 100,
        after: Optional[str] = None,
        order: str = "asc",
    ) -> Any:
        """List items in a conversation."""
        if conversation_id not in self._conversations:
            return type("Response", (), {"data": [], "has_more": False, "last_id": None})()

        messages = self._conversations[conversation_id].get("messages", [])

        # Convert to item format
        items = []
        for msg in messages:
            items.append({
                "id": msg.get("id", "unknown"),
                "role": msg.get("role"),
                "content": msg.get("content"),
            })

        return type("Response", (), {"data": items, "has_more": False, "last_id": None})()

    def delete(self, conversation_id: str, item_id: str) -> None:
        """Delete an item from a conversation."""
        if conversation_id in self._conversations:
            messages = self._conversations[conversation_id].get("messages", [])
            self._conversations[conversation_id]["messages"] = [
                msg for msg in messages if msg.get("id") != item_id
            ]


class LiteLLMClient:
    """Mock client object for LiteLLM to maintain OpenAI interface compatibility."""

    def __init__(self, provider: "LiteLLMProvider"):
        self.conversations = LiteLLMConversationsAPI(provider)


class LiteLLMProvider(ModelProvider):
    """LiteLLM provider for unified model access.

    Uses LiteLLM to provide a unified interface to multiple LLM providers.
    Supports OpenAI, Gemini, Anthropic, and many other providers through
    a single API.
    """

    def __init__(self, max_tool_rounds_per_turn: int = 1) -> None:
        self._validated: bool = False
        self._mock_client: Optional[LiteLLMClient] = None
        self._call_id = 0
        self._max_tool_rounds = max_tool_rounds_per_turn
        self._runtime = None  # Lazy initialization

        # Configure LiteLLM settings
        litellm.drop_params = True  # Drop unsupported params instead of erroring
        litellm.set_verbose = False  # Reduce noise in logs

    def _get_runtime(self):
        """Lazily initialize and return the ToolRuntime."""
        if self._runtime is None:
            from agent.tools.runtime import ToolRuntime
            self._runtime = ToolRuntime()
        return self._runtime

    def _get_client(self) -> LiteLLMClient:
        """Get or create the mock client."""
        if self._mock_client is None:
            self._mock_client = LiteLLMClient(self)
        return self._mock_client

    @property
    def client(self) -> LiteLLMClient:
        """Return the mock client for OpenAI compatibility."""
        if not self._validated:
            raise RuntimeError(
                "LiteLLM provider not validated. Call validate() before accessing client."
            )
        return self._get_client()

    def _detect_provider_from_model(self, model: str) -> str:
        """Detect the provider from the model name."""
        model_lower = model.lower()

        if any(p in model_lower for p in ["gemini", "gemma", "learnlm", "imagen"]):
            return "gemini"
        if any(p in model_lower for p in ["claude", "anthropic"]):
            return "anthropic"
        if any(p in model_lower for p in ["gpt", "o1", "o3", "davinci", "curie", "babbage", "ada"]):
            return "openai"

        # Default to OpenAI
        return "openai"

    def _get_litellm_model_name(self, model: str) -> str:
        """Convert model name to LiteLLM format if needed.

        LiteLLM uses prefixes for non-OpenAI models:
        - gemini/gemini-pro -> Gemini
        - claude-3-opus -> Anthropic (no prefix needed)
        - gpt-4 -> OpenAI (no prefix needed)
        """
        model_lower = model.lower()

        # Gemini models need the gemini/ prefix
        if any(p in model_lower for p in ["gemini", "gemma", "learnlm"]):
            if not model.startswith("gemini/"):
                return f"gemini/{model}"

        return model

    def _get_required_api_key_env(self, model: str) -> tuple[str, str]:
        """Get the required API key environment variable for a model.

        Returns:
            Tuple of (env_var_name, provider_name)
        """
        provider = self._detect_provider_from_model(model)

        if provider == "gemini":
            return "GEMINI_API_KEY", "Google Gemini"
        if provider == "anthropic":
            return "ANTHROPIC_API_KEY", "Anthropic"
        # Default to OpenAI
        return "OPENAI_API_KEY", "OpenAI"

    def validate(self, model: str = None) -> None:
        """Validate that required API keys are set.

        Args:
            model: Optional model name to validate specific provider.
                   If not provided, validates OpenAI as default.
        """
        # Determine which API key to check
        if model:
            env_var, provider_name = self._get_required_api_key_env(model)
        else:
            env_var, provider_name = "OPENAI_API_KEY", "OpenAI"

        api_key = os.getenv(env_var)
        if not api_key or not api_key.strip():
            raise ValueError(
                f"{env_var} environment variable is required but not set. "
                f"Please ensure your .env file contains {env_var}=your-actual-key-here "
                "or set the environment variable directly."
            )

        # Test connectivity with a minimal call
        try:
            test_model = model or "gpt-4o-mini"
            litellm_model = self._get_litellm_model_name(test_model)

            # Use a simple completion to test connectivity
            response = completion(
                model=litellm_model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5,
            )
            self._validated = True
            agent_logger.info(f"LiteLLM provider validated successfully for {provider_name}")
        except Exception as e:
            raise ValueError(
                f"Failed to validate {provider_name} API key via LiteLLM: {e}. "
                "Please ensure your API key is valid."
            )

    def _convert_tools_to_litellm(self, tools: Optional[List]) -> Optional[List]:
        """Convert tool definitions to LiteLLM format.

        LiteLLM uses OpenAI's tool format, so this is mostly passthrough.
        """
        if not tools:
            return None

        litellm_tools = []
        for tool in tools:
            if isinstance(tool, dict):
                if "function" in tool:
                    # Already in OpenAI format
                    litellm_tools.append(tool)
                elif "name" in tool and "parameters" in tool:
                    # Convert to OpenAI format
                    litellm_tools.append({
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "parameters": tool["parameters"],
                        },
                    })

        return litellm_tools if litellm_tools else None

    def call(
        self,
        *,
        model: str,
        input_messages: Optional[Union[str, List]] = None,
        conversation_id: Optional[str] = None,
        tools: Optional[List] = None,
        max_output_tokens: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Call the model via LiteLLM.

        Args:
            model: Model name (e.g., 'gpt-4', 'gemini-pro')
            input_messages: String or list of message dicts
            conversation_id: Conversation ID for context management
            tools: Tool definitions
            max_output_tokens: Maximum tokens in response
            timeout_ms: Request timeout in milliseconds
            reasoning_effort: Reasoning effort level for supported models
            extra: Provider-specific parameters

        Returns:
            Response object with OpenAI-compatible structure
        """
        if not self._validated:
            raise RuntimeError(
                "LiteLLM provider not validated. Call validate() before making API calls."
            )

        # Get the LiteLLM model name
        litellm_model = self._get_litellm_model_name(model)

        # Build messages from conversation history
        messages = []
        if conversation_id and self._mock_client:
            conv = self._mock_client.conversations._conversations.get(conversation_id)
            if conv:
                for msg in conv.get("messages", []):
                    messages.append({
                        "role": msg["role"],
                        "content": msg["content"],
                    })

        # Add new input messages
        if input_messages:
            if isinstance(input_messages, str):
                messages.append({"role": "user", "content": input_messages})
            elif isinstance(input_messages, list):
                for msg in input_messages:
                    if isinstance(msg, dict):
                        # Handle function_call_output format
                        if msg.get("type") == "function_call_output":
                            messages.append({
                                "role": "tool",
                                "tool_call_id": msg.get("call_id", ""),
                                "content": msg.get("output", ""),
                            })
                        elif "role" in msg:
                            content = msg.get("content", "")
                            if isinstance(content, list):
                                # Extract text from content array
                                text_parts = []
                                for part in content:
                                    if isinstance(part, dict) and "text" in part:
                                        text_parts.append(part["text"])
                                content = "\n".join(text_parts)
                            messages.append({"role": msg["role"], "content": content})

        # If no messages but we have a conversation, use continuation prompt
        if not messages and conversation_id:
            messages.append({"role": "user", "content": "Continue"})

        if not messages:
            raise ValueError("Must provide either input_messages or conversation_id with history")

        # Build completion kwargs
        kwargs: Dict[str, Any] = {
            "model": litellm_model,
            "messages": messages,
        }

        # Add tools if provided
        litellm_tools = self._convert_tools_to_litellm(tools)
        if litellm_tools:
            kwargs["tools"] = litellm_tools
            kwargs["tool_choice"] = "auto"

        if max_output_tokens:
            kwargs["max_tokens"] = max_output_tokens

        if timeout_ms:
            kwargs["timeout"] = timeout_ms / 1000.0  # Convert to seconds

        # Handle reasoning effort for supported models
        if reasoning_effort:
            model_lower = model.lower()
            # OpenAI o1/o3 models
            if any(p in model_lower for p in ["o1", "o3"]):
                kwargs["reasoning_effort"] = reasoning_effort
            # Gemini models with thinking
            elif "gemini-3" in model_lower or "gemini-2" in model_lower:
                # LiteLLM may pass this through to Gemini
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": 8000}

        if extra:
            kwargs.update(extra)

        agent_logger.info(
            f"LiteLLM API request: model={litellm_model}, messages={len(messages)}, "
            f"tools={len(litellm_tools) if litellm_tools else 0}"
        )

        # Increment call ID
        self._call_id += 1
        current_call_id = f"litellm-{self._call_id}"

        try:
            # Make the completion call
            response = completion(**kwargs)

            # Handle tool calls if present
            tool_calls_made = []
            tool_round = 0
            current_messages = messages.copy()

            while tool_round < self._max_tool_rounds:
                # Check for tool calls in response
                choice = response.choices[0] if response.choices else None
                if not choice or not choice.message:
                    break

                tool_calls = getattr(choice.message, "tool_calls", None)
                if not tool_calls:
                    break

                tool_round += 1
                agent_logger.info(f"Tool calling round {tool_round}/{self._max_tool_rounds}")

                # Add assistant message with tool calls to history
                assistant_msg = {
                    "role": "assistant",
                    "content": choice.message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
                current_messages.append(assistant_msg)

                # Execute tool calls
                for tc in tool_calls:
                    function_name = tc.function.name
                    try:
                        function_args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        function_args = {}

                    agent_logger.info(f"Executing function: {function_name}")
                    agent_logger.info(f"Function arguments: {json.dumps(function_args)}")

                    # Execute via Runtime
                    tool_result = self._get_runtime().execute(function_name, function_args)

                    tool_calls_made.append({
                        "id": tc.id,
                        "name": function_name,
                        "arguments": function_args,
                        "output": tool_result,
                    })

                    # Add tool result to messages
                    result_content = json.dumps(tool_result) if isinstance(tool_result, dict) else str(tool_result)
                    current_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_content,
                    })

                # Continue conversation with tool results
                kwargs["messages"] = current_messages
                response = completion(**kwargs)

            # Convert response to OpenAI-compatible format
            converted = self._convert_response(response, current_call_id, tool_calls_made)

            # Update conversation history if we have a conversation_id
            if conversation_id and self._mock_client:
                conv = self._mock_client.conversations._conversations.get(conversation_id)
                if conv:
                    # Add the final assistant message
                    conv["messages"].append({
                        "role": "assistant",
                        "content": converted.output_text or "",
                        "id": f"msg-{self._call_id}",
                    })

            return converted

        except Exception as e:
            agent_logger.error(f"LiteLLM API call failed: {e}")
            raise

    def _convert_response(
        self, response: Any, request_id: str, tool_calls_made: List[Dict]
    ) -> Any:
        """Convert LiteLLM response to OpenAI-compatible format.

        Args:
            response: LiteLLM completion response
            request_id: Unique identifier for this request
            tool_calls_made: List of tool calls that were executed

        Returns:
            Object with OpenAI Responses API compatible structure
        """
        # Extract text from response
        text = ""
        choice = response.choices[0] if response.choices else None
        if choice and choice.message:
            text = choice.message.content or ""

        # Extract usage information
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
        total_tokens = getattr(usage, "total_tokens", 0) if usage else 0

        # LiteLLM may provide cached tokens info
        cached_tokens = 0
        if usage:
            # Check for various cache token fields
            cached_tokens = getattr(usage, "prompt_tokens_details", {})
            if isinstance(cached_tokens, dict):
                cached_tokens = cached_tokens.get("cached_tokens", 0)
            elif hasattr(cached_tokens, "cached_tokens"):
                cached_tokens = cached_tokens.cached_tokens
            else:
                cached_tokens = 0

        # Extract tool calls from response (if any remaining unexecuted ones)
        response_tool_calls = []
        if choice and choice.message:
            tc_list = getattr(choice.message, "tool_calls", None)
            if tc_list:
                for tc in tc_list:
                    response_tool_calls.append(
                        type(
                            "ToolCall",
                            (),
                            {
                                "id": tc.id,
                                "type": "function",
                                "call_id": tc.id,
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        )()
                    )

        # Build output items
        output_items = []

        # Add executed tool calls to output
        for tc in tool_calls_made:
            output_items.append(
                type(
                    "ToolCallItem",
                    (),
                    {
                        "type": "tool_call",
                        "call_id": tc["id"],
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"]),
                        "output": json.dumps(tc["output"]) if isinstance(tc["output"], dict) else str(tc["output"]),
                        "error": None,
                    },
                )()
            )

        # Add any unexecuted tool calls
        for tc in response_tool_calls:
            output_items.append(tc)

        # Build the response object
        return type(
            "LiteLLMResponse",
            (),
            {
                "id": request_id,
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
                        "input_tokens_details": type(
                            "InputTokensDetails",
                            (),
                            {"cached_tokens": cached_tokens},
                        )(),
                    },
                )(),
                "tool_outputs": [],
                "output": output_items,
                "tool_calls": response_tool_calls,
            },
        )()
