from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Union

import google.generativeai as genai
import requests
from google.generativeai.types import GenerateContentResponse

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

    def __init__(self, max_tool_rounds_per_turn: int = 3) -> None:
        # Configuration is done lazily to avoid issues if validation fails
        self._configured: bool = False
        self._validated: bool = False
        self._mock_client = GeminiClient()
        self._mcp_request_id = 0  # JSON-RPC request ID counter for MCP calls
        self._gemini_call_id = 0  # Counter for unique Gemini response IDs
        self._max_tool_rounds = (
            max_tool_rounds_per_turn  # Allow multiple tool calls per turn
        )
        self._tool_cache: Dict[str, list] = (
            {}
        )  # Cache for MCP tool definitions by server URL
        self._chat_sessions: Dict[str, Any] = {}  # Cache ChatSession objects by conversation_id

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
        extra: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Call the Gemini API.

        Args:
            model: Gemini model name (e.g., 'gemini-3-pro-preview')
            input_messages: String or list of message dicts
            conversation_id: Not used for Gemini (conversations managed externally)
            tools: MCP tools configuration (converted to Gemini function calling format)
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

        # Create generation config
        generation_config = {}
        if max_output_tokens:
            generation_config["max_output_tokens"] = max_output_tokens

        # Convert MCP tools to Gemini function declarations
        gemini_tools = None
        mcp_server_url = None
        if tools and len(tools) > 0:
            gemini_tools = self._convert_mcp_tools_to_gemini(tools)
            # Store MCP server URL for tool execution
            if isinstance(tools[0], dict) and tools[0].get("type") == "mcp":
                mcp_server_url = tools[0].get("server_url")

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
                agent_logger.debug(f"Created new chat session for conversation {conversation_id}")

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
            mcp_calls_made = []
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

                        # Execute via MCP if server URL is available
                        if mcp_server_url:
                            mcp_result = self._execute_mcp_tool(
                                mcp_server_url, function_name, function_args
                            )

                            # Track full MCP result for final response
                            mcp_calls_made.append(
                                {
                                    "name": function_name,
                                    "arguments": function_args,
                                    "output": mcp_result,
                                }
                            )

                            # Extract simplified result for Gemini
                            # MCP returns: {"content": [...], "structuredContent": {"result": "..."}}
                            # Gemini needs just the result
                            gemini_result = {}
                            if isinstance(mcp_result, dict):
                                # Prefer structuredContent.result - it's already clean
                                if "structuredContent" in mcp_result:
                                    gemini_result = mcp_result["structuredContent"]
                                # Fallback: extract text from content array
                                elif "content" in mcp_result and isinstance(
                                    mcp_result["content"], list
                                ):
                                    if len(mcp_result["content"]) > 0:
                                        first_item = mcp_result["content"][0]
                                        if (
                                            isinstance(first_item, dict)
                                            and "text" in first_item
                                        ):
                                            gemini_result = {
                                                "result": first_item["text"]
                                            }
                                        else:
                                            gemini_result = {"result": str(first_item)}
                                # Last resort: stringify the whole result
                                else:
                                    gemini_result = {"result": json.dumps(mcp_result)}
                            else:
                                gemini_result = {"result": str(mcp_result)}

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
                        else:
                            agent_logger.error(
                                f"Cannot execute function {function_name}: MCP server URL not available"
                            )
                            function_responses.append(
                                {
                                    "function_call": fc,
                                    "function_response": {
                                        "name": function_name,
                                        "response": {
                                            "error": "MCP server not configured"
                                        },
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
                    f"Completed {tool_round} tool calling round(s) with {len(mcp_calls_made)} total MCP call(s)"
                )

            # Convert Gemini response to OpenAI-compatible format
            converted_response = self._convert_response(
                response, request_id=current_call_id
            )

            # Add MCP call information to output
            if mcp_calls_made:
                output_items = list(getattr(converted_response, "output", []))
                for mcp_call in mcp_calls_made:
                    output_items.append(
                        type(
                            "MCPItem",
                            (),
                            {
                                "type": "mcp_call",
                                "name": mcp_call["name"],
                                "arguments": json.dumps(mcp_call["arguments"]),
                                "output": json.dumps(mcp_call["output"]),
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

    def _parse_sse_response(self, response_text: str) -> dict:
        """Parse Server-Sent Events format response.

        Args:
            response_text: Raw SSE response text

        Returns:
            Parsed JSON data from SSE
        """
        lines = response_text.strip().split("\n")
        for line in lines:
            if line.startswith("data: "):
                data_str = line[6:].strip()
                try:
                    return json.loads(data_str)
                except json.JSONDecodeError:
                    continue
        raise ValueError("No valid JSON data found in Server-Sent Events response")

    def _fetch_mcp_tools(self, server_url: str) -> list:
        """Fetch tool definitions from MCP server.

        Args:
            server_url: MCP server URL (e.g., https://example.ngrok.io/mcp/)

        Returns:
            List of tool definitions from MCP server
        """
        try:
            # Normalize URL - remove trailing slash
            url = server_url.rstrip("/")

            self._mcp_request_id += 1
            # Use JSON-RPC 2.0 format for MCP protocol
            payload = {
                "jsonrpc": "2.0",
                "id": self._mcp_request_id,
                "method": "tools/list",
                "params": {},
            }

            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }

            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()

            # Handle both JSON and Server-Sent Events responses
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                result = self._parse_sse_response(response.text)
            else:
                result = response.json()

            # Extract tools from JSON-RPC response
            if "result" in result and "tools" in result["result"]:
                tools = result["result"]["tools"]
                agent_logger.info(f"Fetched {len(tools)} tools from MCP server")
                return tools
            else:
                agent_logger.warning(f"Unexpected MCP response format: {result}")
                return []

        except Exception as e:
            agent_logger.error(
                f"Failed to fetch tools from MCP server {server_url}: {e}"
            )
            return []

    def _execute_mcp_tool(
        self, server_url: str, tool_name: str, arguments: dict
    ) -> dict:
        """Execute a tool call via MCP server.

        Args:
            server_url: MCP server URL
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool execution result
        """
        try:
            # Normalize URL - remove trailing slash
            url = server_url.rstrip("/")

            self._mcp_request_id += 1
            # Use JSON-RPC 2.0 format for MCP protocol
            payload = {
                "jsonrpc": "2.0",
                "id": self._mcp_request_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }

            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }

            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()

            # Handle both JSON and Server-Sent Events responses
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                result = self._parse_sse_response(response.text)
            else:
                result = response.json()

            if "result" in result:
                agent_logger.info(f"MCP tool {tool_name} executed successfully")
                return result["result"]
            else:
                agent_logger.error(f"Unexpected MCP tool call response: {result}")
                return {"error": "Unexpected response format"}

        except Exception as e:
            agent_logger.error(f"Failed to execute MCP tool {tool_name}: {e}")
            return {"error": str(e)}

    def _convert_mcp_schema_to_gemini(self, mcp_schema: dict) -> dict:
        """Convert MCP JSON schema to Gemini parameter format.

        Args:
            mcp_schema: MCP tool input schema (JSON Schema format)

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

        mcp_type = mcp_schema.get("type", "object").lower()
        gemini_type = type_mapping.get(mcp_type, "OBJECT")

        gemini_schema = {
            "type_": gemini_type,
        }

        # Add description if present
        if "description" in mcp_schema:
            gemini_schema["description"] = mcp_schema["description"]

        # Convert properties recursively if present
        if "properties" in mcp_schema:
            gemini_properties = {}
            for prop_name, prop_schema in mcp_schema["properties"].items():
                # Recursively convert nested schemas
                if isinstance(prop_schema, dict):
                    gemini_properties[prop_name] = self._convert_mcp_schema_to_gemini(
                        prop_schema
                    )
                else:
                    gemini_properties[prop_name] = {
                        "type_": "STRING"
                    }  # Default fallback
            gemini_schema["properties"] = gemini_properties

        if "required" in mcp_schema:
            gemini_schema["required"] = mcp_schema["required"]

        # Handle array items
        if "items" in mcp_schema and isinstance(mcp_schema["items"], dict):
            gemini_schema["items"] = self._convert_mcp_schema_to_gemini(
                mcp_schema["items"]
            )

        return gemini_schema

    def _convert_mcp_tools_to_gemini(self, tools: list) -> Optional[list]:
        """Convert MCP tool configuration to Gemini function declarations.

        Args:
            tools: List containing MCP configuration dict

        Returns:
            List of Gemini function declarations or None
        """
        # Check if tools is an MCP configuration
        if not tools or len(tools) == 0:
            return None

        if not isinstance(tools[0], dict):
            return None

        tool_config = tools[0]
        if tool_config.get("type") != "mcp":
            agent_logger.warning("Tools provided but not in MCP format")
            return None

        server_url = tool_config.get("server_url")
        if not server_url:
            agent_logger.error("MCP configuration missing server_url")
            return None

        # Check cache first to avoid redundant fetches
        if server_url in self._tool_cache:
            cached_tools = self._tool_cache[server_url]
            agent_logger.debug(
                f"Using cached tools for {server_url} ({len(cached_tools)} tools)"
            )
            return cached_tools

        # Fetch tools from MCP server
        mcp_tools = self._fetch_mcp_tools(server_url)
        if not mcp_tools:
            agent_logger.warning("No tools available from MCP server")
            return None

        # Convert to Gemini function declarations
        gemini_functions = []
        for tool in mcp_tools:
            function_decl = {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
            }

            # Convert input schema if present
            if "inputSchema" in tool:
                function_decl["parameters"] = self._convert_mcp_schema_to_gemini(
                    tool["inputSchema"]
                )
            else:
                # No parameters
                function_decl["parameters"] = {"type": "object", "properties": {}}

            gemini_functions.append(function_decl)

        # Cache the converted tools for future use
        self._tool_cache[server_url] = gemini_functions
        agent_logger.info(
            f"Converted and cached {len(gemini_functions)} MCP tools to Gemini format"
        )
        return gemini_functions

    def _convert_response(
        self, response: GenerateContentResponse, request_id: str = "gemini-response"
    ) -> Dict[str, Any]:
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
                "output": [],  # MCP calls are added by call() method
            },
        )()
