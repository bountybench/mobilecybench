import json
import os
import subprocess
import time

from dotenv import load_dotenv

from agent.agent_helpers import get_directory_tree
from agent.model_providers import get_model_provider
from agent.prompts.prompts import (
    MISSING_OUTPUT_NUDGE,
    build_detect_prompt,
    build_synthetic_prompt,
)
from agent.tools.runtime import ToolRuntime
from utils.agent_utils import take_screenshot
from utils.logger import agent_logger, logger_manager
from utils.time_tracker import time_tracker
from utils.token_tracker import TokenTracker


class CustomAgent:
    def __init__(
        self,
        model: str,
        max_iterations: int,
        max_model_response_tokens: int,
        screenshot_enabled: bool,
        app_name: str,
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

        self.model = model
        self.max_iterations = max_iterations
        self.max_model_response_tokens = max_model_response_tokens
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

        # Build system prompt
        self._initial_tree_context = get_directory_tree()
        self._instructions = self._get_system_prompt_text(additional_context)

        agent_logger.info("=" * 60)
        agent_logger.info("SYSTEM PROMPT")
        agent_logger.info("=" * 60)
        agent_logger.info(self._instructions)
        agent_logger.info("=" * 60)

        # Create provider (fully configured on construction)
        self.provider = get_model_provider(
            model=model,
            instructions=self._instructions,
            tools=self.runtime.get_tool_definitions(),
            max_output_tokens=max_model_response_tokens,
            timeout_ms=timeout_ms,
            reasoning_effort=reasoning_effort,
        )

        # Use shared logger's file name for consistency
        self.log_file = logger_manager.get_agent_log_file_name()

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

    def _check_exploit_exists(self) -> bool:
        """Check whether exploit.sh exists in the kali container."""
        try:
            result = subprocess.run(
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
            return result.returncode == 0
        except Exception as e:
            agent_logger.warning(f"Failed to check for exploit.sh: {e}")
            return False

    def _finish_run(self, turns: int, final_message: str = None) -> dict:
        """Log summary, archive conversation, and return the result dict."""
        exploit_exists = self._check_exploit_exists()

        agent_logger.info(f"{'=' * 20} RUN COMPLETED {'=' * 20}")
        agent_logger.info(f"Turns: {turns}/{self.max_iterations}")
        agent_logger.info(f"Exploit exists: {exploit_exists}")
        if final_message:
            agent_logger.info(f"Final message: {final_message}")
        agent_logger.info(f"Token totals: {json.dumps(self.token_tracker.totals())}")

        self._archive_conversation()

        return {
            "status": "completed",
            "turns_taken": turns,
            "max_turns": self.max_iterations,
            "exploit_exists": exploit_exists,
            "final_message": final_message,
            "token_totals": self.token_tracker.totals(),
            "log_file": self.log_file,
        }

    def _archive_conversation(self):
        """Archive the conversation log to the agent log."""
        history = self.provider.get_conversation_history()
        agent_logger.info("=" * 60)
        agent_logger.info("FULL CONVERSATION ARCHIVE")
        agent_logger.info("=" * 60)
        agent_logger.info(f"App name: {self.app_name}")
        agent_logger.info(f"Total entries: {len(history)}")

        for idx, entry in enumerate(history, 1):
            agent_logger.info(f"\n--- Entry {idx} ---")
            agent_logger.info(f"{json.dumps(entry, indent=2, default=str)}")

        agent_logger.info("\n" + "=" * 60)

    def run(self) -> dict:
        next_input = "Begin. Read your instructions and start working."

        for turn in range(self.max_iterations):
            agent_logger.info(
                f"{'=' * 20} TURN {turn + 1}/{self.max_iterations} {'=' * 20}"
            )
            agent_logger.info("-" * 40)

            # Add screenshot if enabled
            if self.screenshot_enabled:
                try:
                    screenshot_result = take_screenshot()
                    if screenshot_result.get("success"):
                        # On the first turn, next_input is a string; convert to list
                        if isinstance(next_input, str):
                            next_input = [
                                {
                                    "type": "message",
                                    "role": "user",
                                    "content": next_input,
                                }
                            ]
                        next_input.append(
                            {
                                "type": "message",
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_image",
                                        "image_url": f"data:image/png;base64,{screenshot_result.get('image_data', '')}",
                                    }
                                ],
                            }
                        )
                except Exception as e:
                    agent_logger.error(f"Error taking screenshot: {e}")

            call_input = next_input

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
                        resp = self.provider.call(call_input)
                    print("[Agent] API call completed")
                    break  # Success, exit retry loop
                except Exception as e:
                    error_str = str(e).lower()
                    is_retryable = False
                    retry_delay = base_retry_delay
                    error_type = "Unknown"

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
                self.token_tracker.record_from_openai_response(
                    resp.raw_response, model=self.model
                )
            except Exception as e:
                agent_logger.warning(f"Token tracking failed: {e}")

            # Read normalized response fields
            assistant_text = resp.assistant_text
            function_calls = resp.function_calls
            reasoning_summary = resp.reasoning_summary

            # Log response
            agent_logger.info(
                f"[API RESPONSE - {len(assistant_text)} chars text, "
                f"{len(reasoning_summary)} chars reasoning, {len(function_calls)} tool calls]"
            )

            if reasoning_summary:
                agent_logger.info(f"[REASONING SUMMARY] {reasoning_summary}")
            if assistant_text:
                agent_logger.info(f"[ASSISTANT TEXT] {assistant_text}")
            agent_logger.info("-" * 40)

            # Process function calls (tool use)
            has_tool_call = bool(function_calls)

            # Prepare next_input for the next turn (tool results go here)
            next_input = []

            if function_calls:
                agent_logger.info(f"[TOOL CALLS DETECTED: {len(function_calls)}]")

                for fc in function_calls:
                    agent_logger.info(f"Executing tool: {fc.name}")
                    agent_logger.info(f"Arguments: {fc.arguments}")

                    # Execute using local runtime
                    result = self.runtime.execute(fc.name, fc.arguments)

                    agent_logger.info(f"Result: {result}")

                    # Add tool result to next turn's input
                    next_input.append(
                        {
                            "type": "function_call_output",
                            "call_id": fc.call_id,
                            "output": str(result),
                        }
                    )

            # Detect final submission
            is_final_submission = False
            if assistant_text and assistant_text.strip():
                if assistant_text.strip().endswith("FinalSubmissionCommand"):
                    is_final_submission = True
                else:
                    try:
                        parsed_response = json.loads(assistant_text.strip())
                        if (
                            isinstance(parsed_response, dict)
                            and parsed_response.get("command")
                            == "FinalSubmissionCommand"
                        ):
                            is_final_submission = True
                    except (json.JSONDecodeError, ValueError):
                        pass

            # Handle final submission
            if is_final_submission:
                if not self._check_exploit_exists():
                    agent_logger.warning(
                        "FinalSubmissionCommand received but exploit.sh does not exist"
                    )
                    next_input.append(
                        {
                            "type": "message",
                            "role": "user",
                            "content": (
                                "ERROR: You attempted to submit, but exploit.sh does not exist "
                                "at /app/exploit_files/exploit.sh. Create it and submit again."
                            ),
                        }
                    )
                    continue

                return self._finish_run(
                    turns=turn + 1,
                    final_message=assistant_text,
                )

            # Nudge for missing text and/or tool calls
            has_text = bool(assistant_text and assistant_text.strip())
            missing = []
            if not has_text:
                missing.append(
                    "visible text in Reflection/Plan/Thought/Log/Command format"
                )
            if not has_tool_call:
                missing.append("a tool call")

            if missing:
                nudge_msg = MISSING_OUTPUT_NUDGE.format(
                    turn=turn + 1, missing=" and ".join(missing)
                )
                agent_logger.warning(nudge_msg)
                next_input.append(
                    {
                        "type": "message",
                        "role": "user",
                        "content": nudge_msg,
                    }
                )
                if not has_tool_call:
                    continue  # Can't proceed without tool results

        # Ran out of turns
        return self._finish_run(turns=self.max_iterations)
