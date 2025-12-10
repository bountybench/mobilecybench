import json
import os
import subprocess
import time

from dotenv import load_dotenv

from agent.agent_helpers import get_directory_tree
from agent.model_providers import get_model_provider
from agent.prompts.prompts import (
    AGENT_GOAL,
    APP_CREDENTIALS,
    APP_SERVER_ACCESS,
    BASE_EXAMPLES,
    BASE_INSTRUCTIONS,
    BASE_RESPONSE_FORMAT,
    DETECT_DESCRIPTION,
    STOP_TOKEN,
    TARGET_HOST_EXAMPLE,
)
from utils.agent_utils import take_screenshot
from utils.logger import agent_logger, logger_manager
from utils.mcp_utils import get_mcp_server_config
from utils.time_tracker import time_tracker
from utils.token_tracker import TokenTracker


class CustomAgent:
    def __init__(
        self,
        model: str,
        max_iterations: int,
        max_model_response_tokens: int,
        max_kali_message_tokens: int,
        # TODO need to enforce this before sending off requests
        max_context_length: int,
        screenshot_enabled: bool,
        app_name: str,
        dry_run: bool,
        mcp_config: dict = None,
        system_prompt: str = None,
        timeout_ms: int = 600_000,
        app_server: str = None,
        network_access: bool = True,
        package_name: str = None,
        username: str = None,
        password: str = None,
    ):
        self.dry_run = dry_run

        # Skip provider setup in dry-run mode
        if not self.dry_run:
            # Load environment variables from .env file in the agent directory
            agent_dir = os.path.dirname(os.path.abspath(__file__))
            env_file = os.path.join(agent_dir, ".env")
            if os.path.exists(env_file):
                load_dotenv(env_file, override=True)

            # Auto-detect provider based on model name
            self.provider = get_model_provider(model=model)
            self.provider.validate()

        self.model = model
        self.max_iterations = max_iterations
        self.max_model_response_tokens = max_model_response_tokens
        self.max_kali_message_tokens = max_kali_message_tokens
        self.max_context_length = max_context_length
        self.timeout_ms = timeout_ms
        self.screenshot_enabled = screenshot_enabled
        self.app_server = app_server
        self.network_access = network_access
        self.app_name = app_name
        self.package_name = package_name
        self.username = username
        self.password = password

        # Set up MCP configuration
        self.mcp_config = mcp_config or get_mcp_server_config()

        # Set up system prompt (skip in dry-run mode)
        self.conversation_id = None
        self._initial_tree_context = get_directory_tree()

        if not self.dry_run:
            if system_prompt:
                self.system_prompt = {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                }
            else:
                self.system_prompt = self._get_default_system_prompt()
                agent_logger.info(f"Conversation system prompt: {self.system_prompt}")

            # Initialize conversation with system prompt
            system_content = self.system_prompt["content"][0]["text"]
            conversation = self.provider.client.conversations.create(
                metadata={"app_name": self.app_name, "model": self.model},
                items=[
                    {"type": "message", "role": "system", "content": system_content}
                ],
            )
            self.conversation_id = conversation.id
            agent_logger.info(f"Created conversation: {self.conversation_id}")

            # Fetch directory tree for initial context (will be added in first turn)

        # Use shared logger's file name for consistency
        self.log_file = logger_manager.get_agent_log_file_name()

        # Initialize token tracker (writes per-call JSONL by default)
        self.token_tracker = TokenTracker()

        # Track screenshot item ID to manage context window
        self.screenshot_item_id = None

        agent_logger.info("Agent Run Started")
        agent_logger.info(f"Dry Run: {self.dry_run}")

        agent_logger.info(f"Model: {self.model}")
        agent_logger.info(f"Max Iterations: {self.max_iterations}")
        agent_logger.info(
            f"MCP Server: {self.mcp_config.get('server_url', 'Not configured')}"
        )
        agent_logger.info("=" * 80)

    def _get_default_system_prompt(self) -> dict:
        prompt_parts = [
            DETECT_DESCRIPTION,
            AGENT_GOAL.format(
                package_name=self.package_name, codebase=self._initial_tree_context
            ),
        ]

        if self.network_access and self.app_server:
            prompt_parts.extend([APP_SERVER_ACCESS.format(app_server=self.app_server)])

        if self.username and self.password:
            prompt_parts.extend(
                [APP_CREDENTIALS.format(username=self.username, password=self.password)]
            )

        prompt_parts.extend(
            [
                BASE_RESPONSE_FORMAT.format(stop_token=STOP_TOKEN),
                BASE_INSTRUCTIONS.format(stop_token=STOP_TOKEN),
                BASE_EXAMPLES.format(stop_token=STOP_TOKEN),
            ]
        )

        # Add target host example if provided
        if self.app_server:
            prompt_parts.extend(
                [
                    TARGET_HOST_EXAMPLE.format(
                        resolved_host=self.app_server, stop_token=STOP_TOKEN
                    ),
                ]
            )

        full_prompt = "".join(prompt_parts)

        return {
            "role": "system",
            "content": [{"type": "input_text", "text": full_prompt}],
        }

    def _archive_conversation(self):
        """Archive the full conversation history including all messages to the agent log.

        TODO: Refactor this method into each specific model provider class, as not every
        model provider has the concept of a conversation object (e.g., this is specific
        to OpenAI's Conversations API). This logic should be moved to the provider layer.
        """
        if not self.conversation_id:
            return

        try:
            # Fetch full conversation history with all items (messages)
            conversation_data = self.provider.client.conversations.retrieve(
                conversation_id=self.conversation_id
            )

            # Retrieve all items (messages) with pagination
            all_items = []
            after_id = None

            while True:
                if after_id:
                    items_response = self.provider.client.conversations.items.list(
                        conversation_id=self.conversation_id,
                        limit=100,
                        after=after_id,
                        order="asc",
                    )
                else:
                    items_response = self.provider.client.conversations.items.list(
                        conversation_id=self.conversation_id, limit=100, order="asc"
                    )

                all_items.extend(items_response.data)

                if not items_response.has_more:
                    break

                after_id = items_response.last_id

            # Log conversation data to agent log
            agent_logger.info("=" * 60)
            agent_logger.info("FULL CONVERSATION ARCHIVE")
            agent_logger.info("=" * 60)
            agent_logger.info(f"Conversation ID: {self.conversation_id}")

            # Convert conversation object to dict for proper JSON serialization
            conversation_dict = {
                "id": conversation_data.id,
                "created_at": conversation_data.created_at,
                "metadata": conversation_data.metadata,
                "object": conversation_data.object,
            }

            agent_logger.info(
                f"Conversation metadata: {json.dumps(conversation_dict, indent=2, default=str)}"
            )

            # Log all conversation items (messages)
            agent_logger.info(f"\nTotal items in conversation: {len(all_items)}")
            agent_logger.info("\n" + "=" * 60)
            agent_logger.info("CONVERSATION ITEMS (MESSAGES)")
            agent_logger.info("=" * 60)

            for idx, item in enumerate(all_items, 1):
                agent_logger.info(f"\n--- Item {idx} ---")
                agent_logger.info(f"{json.dumps(item, indent=2, default=str)}")

            agent_logger.info("\n" + "=" * 60)
        except Exception as e:
            agent_logger.warning(f"Failed to archive conversation before deletion: {e}")

    def run(self) -> dict:
        if self.dry_run:
            agent_logger.info("Dry run: Quick return without execution")
            return {
                "status": "This is a dry run. No OpenAI API calls were made.",
                "turns": 0,
                "final_message": None,
                "log_file": self.log_file,
            }

        for turn in range(self.max_iterations):
            agent_logger.info(
                f"{'=' * 20} TURN {turn + 1}/{self.max_iterations} {'=' * 20}"
            )

            agent_logger.info("-" * 40)

            if self.screenshot_enabled:
                try:
                    screenshot_result = take_screenshot()
                    if screenshot_result.get("success"):
                        # Delete previous screenshot to reduce context window size
                        # Keep only the most recent screenshot
                        if self.screenshot_item_id:
                            try:
                                self.provider.client.conversations.items.delete(
                                    conversation_id=self.conversation_id,
                                    item_id=self.screenshot_item_id,
                                )
                                agent_logger.info(
                                    f"Deleted previous screenshot item: {self.screenshot_item_id}"
                                )
                            except Exception as delete_error:
                                agent_logger.warning(
                                    f"Failed to delete screenshot item {self.screenshot_item_id}: {delete_error}"
                                )
                            self.screenshot_item_id = None

                        # Add screenshot directly to the conversation using the conversations API
                        # This avoids breaking the reasoning chain in stateful conversations
                        screenshot_message = {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_image",
                                    "image_url": f"data:image/png;base64,{screenshot_result.get('image_data', '')}",
                                }
                            ],
                        }
                        # Add to conversation using conversations.items.create
                        response = self.provider.client.conversations.items.create(
                            conversation_id=self.conversation_id,
                            items=[screenshot_message],
                        )

                        # Track the new screenshot item ID for future deletion
                        if hasattr(response, "items") and len(response.items) > 0:
                            if hasattr(response.items[0], "id"):
                                self.screenshot_item_id = response.items[0].id

                        agent_logger.info(
                            f"Screenshot added to conversation successfully (item_id: {self.screenshot_item_id})"
                        )
                except Exception as e:
                    agent_logger.error(f"Error taking screenshot: {e}")

            # Use context manager for LLM call timing
            # Retry logic for conversation_locked and rate_limit errors
            max_retries = 5
            base_retry_delay = 10  # seconds

            for attempt in range(max_retries):
                try:
                    with time_tracker.llm_timing(
                        model=self.model,
                        conversation_id=self.conversation_id,
                        turn=turn + 1,
                    ):
                        resp = self.provider.call(
                            model=self.model,
                            conversation_id=self.conversation_id,
                            input_messages=None,  # Passing input_messages causes error when model is in the middle of reasoning
                            tools=[self.mcp_config],
                            max_output_tokens=self.max_model_response_tokens,
                            timeout_ms=self.timeout_ms,
                        )
                    print("[Agent] API call completed")
                    break  # Success, exit retry loop
                except Exception as e:
                    error_str = str(e).lower()
                    is_retryable = False
                    retry_delay = base_retry_delay

                    # Check for conversation_locked error
                    if (
                        "conversation_locked" in error_str
                        or "currently operating on this conversation" in error_str
                    ):
                        is_retryable = True
                        error_type = "Conversation locked"
                        retry_delay = base_retry_delay

                    # Check for rate limit and service unavailable errors
                    elif any(
                        indicator in error_str
                        for indicator in [
                            "rate_limit",
                            "rate limit",
                            "too many requests",
                            "quota exceeded",
                            "429",
                            "503",
                            "service unavailable",
                        ]
                    ):
                        is_retryable = True
                        error_type = "Rate limit / Service unavailable"
                        # Use exponential backoff for rate limits
                        retry_delay = base_retry_delay * (2**attempt)

                    if is_retryable:
                        if attempt < max_retries - 1:
                            agent_logger.warning(
                                f"{error_type} error on attempt {attempt + 1}/{max_retries}. "
                                f"Retrying in {retry_delay} seconds..."
                            )
                            time.sleep(retry_delay)
                            continue
                        else:
                            agent_logger.error(
                                f"{error_type} error after {max_retries} attempts. Giving up."
                            )
                            raise
                    else:
                        # Not a retryable error, re-raise immediately
                        raise

            # Record token usage and cost
            try:
                self.token_tracker.record_from_openai_response(resp, model=self.model)
            except Exception as e:
                agent_logger.warning(f"Token tracking failed: {e}")

            # Process response
            assistant_response = resp.output_text
            agent_logger.info(f"[API RESPONSE - {len(assistant_response)} chars]")
            agent_logger.info(assistant_response)
            agent_logger.info("-" * 40)
            # Log all tool outputs from response
            if hasattr(resp, "tool_outputs") and resp.tool_outputs:
                agent_logger.info(f"[TOOL OUTPUTS - {len(resp.tool_outputs)} outputs]")
                for i, tool_output in enumerate(resp.tool_outputs):
                    agent_logger.info(f"Tool Output {i + 1}:")
                    agent_logger.info(str(tool_output))
                agent_logger.info("-" * 40)

            # Log MCP interactions if any
            has_mcp_call = False
            if hasattr(resp, "output") and resp.output:
                agent_logger.info("[MCP INTERACTIONS]")

                for output_item in resp.output:
                    if (
                        hasattr(output_item, "type")
                        and output_item.type == "mcp_list_tools"
                    ):
                        tools_count = len(getattr(output_item, "tools", []))

                        agent_logger.info(f"MCP Tools Listed: {tools_count} tools")
                        tools = getattr(output_item, "tools", [])
                        for tool in tools:
                            tool_name = getattr(tool, "name", "unknown")
                            tool_desc = getattr(tool, "description", "No description")
                            agent_logger.info(f"  - {tool_name}: {tool_desc}")

                    elif (
                        hasattr(output_item, "type") and output_item.type == "mcp_call"
                    ):
                        has_mcp_call = True
                        name = getattr(output_item, "name", "unknown")
                        arguments = getattr(output_item, "arguments", "")
                        output = getattr(output_item, "output", "")
                        error = getattr(output_item, "error", None)

                        agent_logger.info(f"MCP Call: {name}")
                        agent_logger.info(f"  Arguments: {arguments}")
                        agent_logger.info(f"  Output: {output}")
                        if error:
                            agent_logger.info(f"  Error: {error}")

                agent_logger.info("-" * 40)

            # Check for final submission command
            if assistant_response.strip():
                # Check if the response ends with FinalSubmissionCommand or contains it in JSON format
                is_final_submission = False
                if assistant_response.strip().endswith("FinalSubmissionCommand"):
                    is_final_submission = True
                else:
                    # Try parsing as JSON to check for command field
                    try:
                        parsed_response = json.loads(assistant_response.strip())
                        if (
                            isinstance(parsed_response, dict)
                            and parsed_response.get("command")
                            == "FinalSubmissionCommand"
                        ):
                            is_final_submission = True
                    except (json.JSONDecodeError, ValueError):
                        # Not JSON or invalid JSON, continue with is_final_submission = False
                        pass

                # ENFORCE: Every turn must have a tool call (except final submission)
                if not has_mcp_call and not is_final_submission:
                    warning_msg = (
                        f"WARNING: Turn {turn + 1} did not include any MCP tool call. "
                        "Every turn MUST end with exactly one tool call execution. "
                        "You cannot just write plans or reflections without executing commands. "
                        "Re-read the prompt instructions and execute a command using the MCP tools."
                    )
                    agent_logger.warning(warning_msg)

                    # Add error message to conversation so agent sees it
                    self.provider.client.conversations.items.create(
                        conversation_id=self.conversation_id,
                        items=[
                            {"type": "message", "role": "user", "content": warning_msg}
                        ],
                    )

                    # Continue to next turn to give agent a chance to fix it
                    continue

                if is_final_submission:
                    # Verify that exploit.sh exists before accepting the submission
                    exploit_path = "/app/exploit_files/exploit.sh"
                    exploit_exists = False

                    try:
                        check_result = subprocess.run(
                            [
                                "docker",
                                "exec",
                                "kali-container",
                                "test",
                                "-f",
                                exploit_path,
                            ],
                            capture_output=True,
                            text=True,
                        )
                        exploit_exists = check_result.returncode == 0
                    except Exception as e:
                        agent_logger.warning(f"Failed to check for exploit.sh: {e}")

                    if not exploit_exists:
                        # Exploit file doesn't exist - remind the agent to create it
                        agent_logger.warning(
                            "FinalSubmissionCommand received but exploit.sh does not exist"
                        )

                        # Add a reminder message to the conversation
                        reminder_message = {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": f"ERROR: You attempted to submit, but the exploit.sh file does not exist at {exploit_path}. You must create the exploit.sh file in the exploit_files/ directory before submitting. Please create the exploit.sh file and then submit again.",
                                }
                            ],
                        }

                        try:
                            self.provider.client.conversations.items.create(
                                conversation_id=self.conversation_id,
                                items=[reminder_message],
                            )
                            agent_logger.info("Reminder message added to conversation")
                        except Exception as e:
                            agent_logger.error(f"Failed to add reminder message: {e}")

                        # Continue to next turn instead of completing
                        continue

                    # Exploit exists - proceed with submission
                    agent_logger.info(f"{'=' * 20} RUN COMPLETED {'=' * 20}")
                    agent_logger.info("Status: Final submission received")
                    agent_logger.info(f"Total turns: {turn + 1}")
                    agent_logger.info(f"Final message: {assistant_response}")
                    agent_logger.info(
                        f"Token totals: {json.dumps(self.token_tracker.totals())}"
                    )
                    agent_logger.info(f"Log file: {self.log_file}")

                    # Archive and delete conversation before returning
                    if self.conversation_id:
                        self._archive_conversation()

                        # Now delete the conversation
                        self.provider.client.conversations.delete(
                            conversation_id=self.conversation_id
                        )
                        agent_logger.info(
                            f"Deleted conversation: {self.conversation_id}"
                        )

                    return {
                        "status": "completed",
                        "turns": turn + 1,
                        "final_message": assistant_response,
                        "token_totals": self.token_tracker.totals(),
                        "log_file": self.log_file,
                    }

        # Log completion
        agent_logger.info(f"{'=' * 20} RUN COMPLETED {'=' * 20}")
        agent_logger.info("Status: Maximum iterations reached")
        agent_logger.info(f"Total turns: {self.max_iterations}")
        agent_logger.info(f"Token totals: {json.dumps(self.token_tracker.totals())}")
        agent_logger.info(f"Log file: {self.log_file}")

        # Archive conversation before deletion
        if self.conversation_id:
            self._archive_conversation()

            # Now delete the conversation
            self.provider.client.conversations.delete(
                conversation_id=self.conversation_id
            )
            agent_logger.info(f"Deleted conversation: {self.conversation_id}")

        return {
            "status": "max_iterations_reached",
            "turns": self.max_iterations,
            "final_message": None,
            "token_totals": self.token_tracker.totals(),
            "log_file": self.log_file,
        }
