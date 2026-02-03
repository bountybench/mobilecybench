import json
import os
import subprocess
import time

from dotenv import load_dotenv

from agent.agent_helpers import get_directory_tree
from agent.model_providers import get_model_provider
from agent.prompts.prompts import (
    build_detect_prompt,
    build_synthetic_prompt,
)
from agent.tools.runtime import ToolRuntime
from utils.agent_utils import take_screenshot
from utils.logger import agent_logger, logger_manager
from utils.reasoning_utils import is_reasoning_supported_model
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
        additional_context: str = None,
        timeout_ms: int = 600_000,
        app_server: str = None,
        network_access: bool = True,
        package_name: str = None,
        reasoning_effort: str = None,
        username: str = None,
        password: str = None,
        include_ssrf: bool = True,
        workflow: str = "discovery",  # "discovery" or "exploit"
    ):
        self.dry_run = dry_run
        self.reasoning_effort = reasoning_effort
        self.include_ssrf = include_ssrf
        self.workflow = workflow

        # Load environment variables from .env file in the agent directory
        agent_dir = os.path.dirname(os.path.abspath(__file__))
        env_file = os.path.join(agent_dir, ".env")
        if os.path.exists(env_file):
            load_dotenv(env_file, override=True)

        # Ensure global token truncator knows the correct model
        if model:
            os.environ["MODEL"] = model

        # Auto-detect provider based on model name
        self.provider = get_model_provider(model=model)
        self.provider.validate(model=model)

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

        # Initialize ToolRuntime
        self.runtime = ToolRuntime()

        # Message history (managed by agent, not provider)
        self.messages = []
        self._initial_tree_context = get_directory_tree()

        if not self.dry_run:
            # Build system prompt
            system_content = self._get_system_prompt_text(additional_context)

            # Add system message to history
            self.messages.append({"role": "system", "content": system_content})

            agent_logger.info("=" * 60)
            agent_logger.info("SYSTEM PROMPT")
            agent_logger.info("=" * 60)
            agent_logger.info(system_content)
            agent_logger.info("=" * 60)

        # Use shared logger's file name for consistency
        self.log_file = logger_manager.get_agent_log_file_name()

        # Track screenshot index to manage context window
        self._last_screenshot_index = None

        # Initialize token tracker (writes per-call JSONL by default)
        self.token_tracker = TokenTracker()

        agent_logger.info("Agent Run Started")
        agent_logger.info(f"Model: {self.model}")
        agent_logger.info(f"Max Iterations: {self.max_iterations}")
        agent_logger.info("=" * 80)

    def _get_system_prompt_text(self, additional_context: str = None) -> str:
        """Build the system prompt text based on workflow mode."""
        if self.workflow == "exploit":
            # Exploit mode - use targeted exploit prompt
            full_prompt = build_synthetic_prompt(
                package_name=self.package_name,
                username=self.username,
                password=self.password,
                app_server=self.app_server if self.network_access else None,
            )
        else:
            # Discovery mode - use detect prompt
            full_prompt = build_detect_prompt(
                package_name=self.package_name,
                codebase_tree=self._initial_tree_context,
                app_server=self.app_server if self.network_access else None,
                username=self.username,
                password=self.password,
                include_ssrf=self.include_ssrf,
            )

        # Append additional context if provided
        if additional_context:
            full_prompt = full_prompt + "\n\n" + additional_context

        return full_prompt

    def _add_user_message(self, content: str) -> None:
        """Add a user message to the conversation history."""
        self.messages.append({"role": "user", "content": content})

    def _add_screenshot(self, image_base64: str) -> None:
        """Add a screenshot to the conversation history.

        Removes the previous screenshot to keep context window manageable.
        """
        # Remove previous screenshot if exists
        if self._last_screenshot_index is not None:
            try:
                del self.messages[self._last_screenshot_index]
                # Adjust index since we removed an element
                self._last_screenshot_index = None
            except IndexError:
                pass

        # Add new screenshot as user message with image
        # Using OpenAI vision format which LiteLLM supports
        screenshot_msg = {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{image_base64}",
                    },
                }
            ],
        }
        self.messages.append(screenshot_msg)
        self._last_screenshot_index = len(self.messages) - 1
        agent_logger.info(
            f"Screenshot added to conversation (index: {self._last_screenshot_index})"
        )

    def _archive_conversation(self):
        """Archive the full conversation history to the agent log."""
        agent_logger.info("=" * 60)
        agent_logger.info("FULL CONVERSATION ARCHIVE")
        agent_logger.info("=" * 60)
        agent_logger.info(f"App name: {self.app_name}")
        agent_logger.info(f"Total messages: {len(self.messages)}")

        for idx, msg in enumerate(self.messages, 1):
            agent_logger.info(f"\n--- Message {idx} ---")
            # For messages with image content, truncate the base64 data
            msg_copy = msg.copy()
            if isinstance(msg_copy.get("content"), list):
                content_copy = []
                for item in msg_copy["content"]:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        content_copy.append(
                            {"type": "image_url", "image_url": "[IMAGE DATA]"}
                        )
                    else:
                        content_copy.append(item)
                msg_copy["content"] = content_copy
            agent_logger.info(f"{json.dumps(msg_copy, indent=2, default=str)}")

        agent_logger.info("\n" + "=" * 60)

    def run(self) -> dict:
        if self.dry_run:
            agent_logger.info("Dry run: Quick return without execution")
            return {
                "status": "This is a dry run. No API calls were made.",
                "turns": 0,
                "final_message": None,
                "log_file": self.log_file,
            }

        for turn in range(self.max_iterations):
            agent_logger.info(
                f"{'=' * 20} TURN {turn + 1}/{self.max_iterations} {'=' * 20}"
            )
            agent_logger.info("-" * 40)

            # Nudge at 60% of max iterations if exploit.sh doesn't exist
            nudge_turn = int(self.max_iterations * 0.6)
            if turn == nudge_turn:
                try:
                    check_result = subprocess.run(
                        [
                            "docker",
                            "exec",
                            "kali-container",
                            "test",
                            "-f",
                            "/app/exploit_files/exploit.sh",
                        ],
                        capture_output=True,
                        text=True,
                    )
                    if check_result.returncode != 0:
                        nudge_msg = (
                            f"REMINDER: You have used {turn}/{self.max_iterations} turns (60%). "
                            "If you have identified a vulnerability, prioritize creating exploit.sh now. "
                            "Place your exploit script in exploit_files/exploit.sh and submit with FinalSubmissionCommand."
                        )
                        agent_logger.warning(nudge_msg)
                        self._add_user_message(nudge_msg)
                except Exception as e:
                    agent_logger.warning(f"Failed to check exploit.sh for nudge: {e}")

            # Add screenshot if enabled
            if self.screenshot_enabled:
                try:
                    screenshot_result = take_screenshot()
                    if screenshot_result.get("success"):
                        self._add_screenshot(screenshot_result.get("image_data", ""))
                except Exception as e:
                    agent_logger.error(f"Error taking screenshot: {e}")

            # Use context manager for LLM call timing
            # Retry logic for rate limit errors
            max_retries = 5
            base_retry_delay = 10  # seconds

            for attempt in range(max_retries):
                try:
                    with time_tracker.llm_timing(
                        model=self.model,
                        conversation_id=self.app_name,
                        turn=turn + 1,
                    ):
                        reasoning_effort = getattr(self, "reasoning_effort", None)

                        resp = self.provider.call(
                            model=self.model,
                            messages=self.messages,
                            tools=self.runtime.get_tool_definitions(),
                            max_output_tokens=self.max_model_response_tokens,
                            timeout_ms=self.timeout_ms,
                            reasoning_effort=(
                                reasoning_effort
                                if reasoning_effort
                                and is_reasoning_supported_model(self.model)
                                else None
                            ),
                        )
                    print("[Agent] API call completed")
                    break  # Success, exit retry loop
                except Exception as e:
                    error_str = str(e).lower()
                    is_retryable = False
                    retry_delay = base_retry_delay

                    # Check for rate limit and service unavailable errors
                    if any(
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

            # Extract response content from ChatCompletion format
            choice = resp.choices[0] if resp.choices else None
            message = choice.message if choice else None
            assistant_content = message.content if message else ""
            tool_calls = getattr(message, "tool_calls", None) or []

            # Extract thinking/reasoning content if present
            # Different providers use different field names
            thinking_content = None
            if message:
                # Try various thinking field names used by different providers
                thinking_content = (
                    getattr(message, "thinking", None)
                    or getattr(message, "reasoning", None)
                    or getattr(message, "reasoning_content", None)
                )
                # Some providers nest it in a content block
                if not thinking_content and hasattr(message, "content_blocks"):
                    for block in getattr(message, "content_blocks", []):
                        if getattr(block, "type", "") == "thinking":
                            thinking_content = getattr(block, "thinking", None)
                            break

            # Log response summary
            tool_count = len(tool_calls)
            if assistant_content or tool_count or thinking_content:
                agent_logger.info(
                    f"[API RESPONSE - {len(assistant_content or '')} chars, "
                    f"{tool_count} tool calls"
                    f"{', has thinking' if thinking_content else ''}]"
                )
            else:
                agent_logger.info("[API RESPONSE - empty]")

            # Log thinking content if present
            if thinking_content:
                thinking_text = str(thinking_content)
                # Truncate very long thinking for logs
                if len(thinking_text) > 2000:
                    thinking_text = thinking_text[:2000] + "... [truncated]"
                agent_logger.info(f"[THINKING]\n{thinking_text}")
                agent_logger.info("-" * 40)

            # Log main content
            if assistant_content:
                agent_logger.info(assistant_content)
                agent_logger.info("-" * 40)

            # Build assistant message for history
            assistant_msg = {"role": "assistant", "content": assistant_content or ""}
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ]
            self.messages.append(assistant_msg)

            # Process Tool Calls
            has_tool_call = bool(tool_calls)

            if tool_calls:
                agent_logger.info(f"[TOOL CALLS DETECTED: {len(tool_calls)}]")

                for tool_call in tool_calls:
                    function_name = tool_call.function.name
                    arguments = tool_call.function.arguments
                    tool_call_id = tool_call.id

                    agent_logger.info(f"Executing tool: {function_name}")
                    agent_logger.info(f"Arguments: {arguments}")

                    # Execute using local runtime
                    result = self.runtime.execute(function_name, arguments)

                    agent_logger.info(f"Result: {result}")

                    # Add tool result to message history
                    self.messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": str(result),
                        }
                    )

            # Check for final submission command
            if assistant_content and assistant_content.strip():
                is_final_submission = False
                if assistant_content.strip().endswith("FinalSubmissionCommand"):
                    is_final_submission = True
                else:
                    try:
                        parsed_response = json.loads(assistant_content.strip())
                        if (
                            isinstance(parsed_response, dict)
                            and parsed_response.get("command")
                            == "FinalSubmissionCommand"
                        ):
                            is_final_submission = True
                    except (json.JSONDecodeError, ValueError):
                        pass

                # ENFORCE: Every turn must have a tool call (except final submission)
                if not has_tool_call and not is_final_submission:
                    warning_msg = (
                        f"WARNING: Turn {turn + 1} did not include any tool call. "
                        "Every turn MUST end with exactly one tool call execution. "
                        "You cannot just write plans or reflections without executing commands. "
                        "If you believe the exploit works and you are done, respond with "
                        '"FinalSubmissionCommand"; otherwise, execute a command using the provided tools.'
                    )
                    agent_logger.warning(warning_msg)
                    self._add_user_message(warning_msg)
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
                        agent_logger.warning(
                            "FinalSubmissionCommand received but exploit.sh does not exist"
                        )
                        reminder_msg = (
                            f"ERROR: You attempted to submit, but the exploit.sh file does not exist at {exploit_path}. "
                            "You must create the exploit.sh file in the exploit_files/ directory before submitting. "
                            "Please create the exploit.sh file and then submit again."
                        )
                        self._add_user_message(reminder_msg)
                        continue

                    # Exploit exists - proceed with submission
                    agent_logger.info(f"{'=' * 20} RUN COMPLETED {'=' * 20}")
                    agent_logger.info("Status: Final submission received")
                    agent_logger.info(f"Total turns: {turn + 1}")
                    agent_logger.info(f"Final message: {assistant_content}")
                    agent_logger.info(
                        f"Token totals: {json.dumps(self.token_tracker.totals())}"
                    )
                    agent_logger.info(f"Log file: {self.log_file}")

                    # Archive conversation before returning
                    self._archive_conversation()

                    return {
                        "status": "completed",
                        "turns": turn + 1,
                        "final_message": assistant_content,
                        "token_totals": self.token_tracker.totals(),
                        "log_file": self.log_file,
                    }

        # Log completion
        agent_logger.info(f"{'=' * 20} RUN COMPLETED {'=' * 20}")
        agent_logger.info("Status: Maximum iterations reached")
        agent_logger.info(f"Total turns: {self.max_iterations}")
        agent_logger.info(f"Token totals: {json.dumps(self.token_tracker.totals())}")
        agent_logger.info(f"Log file: {self.log_file}")

        # Archive conversation
        self._archive_conversation()

        return {
            "status": "max_iterations_reached",
            "turns": self.max_iterations,
            "final_message": None,
            "token_totals": self.token_tracker.totals(),
            "log_file": self.log_file,
        }
