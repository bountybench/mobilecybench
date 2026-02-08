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
        thinking_budget: int = None,
        username: str = None,
        password: str = None,
        include_ssrf: bool = True,
        workflow: str = "discovery",  # "discovery" or "exploit"
    ):
        self.dry_run = dry_run
        self.reasoning_effort = reasoning_effort
        self.thinking_budget = thinking_budget
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

        # Responses API state (OpenAI-specific; TODO in base.py for potential multi-provider plan)
        self._initial_tree_context = get_directory_tree()
        self._instructions = None  # System prompt (set once)
        self._previous_response_id = None  # Conversation continuity
        self._conversation_log = []  # For archiving

        if not self.dry_run:
            # Build system prompt as instructions
            self._instructions = self._get_system_prompt_text(additional_context)

            agent_logger.info("=" * 60)
            agent_logger.info("SYSTEM PROMPT")
            agent_logger.info("=" * 60)
            agent_logger.info(self._instructions)
            agent_logger.info("=" * 60)

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

    def _archive_conversation(self):
        """Archive the conversation log to the agent log."""
        agent_logger.info("=" * 60)
        agent_logger.info("FULL CONVERSATION ARCHIVE")
        agent_logger.info("=" * 60)
        agent_logger.info(f"App name: {self.app_name}")
        agent_logger.info(f"Total entries: {len(self._conversation_log)}")

        for idx, entry in enumerate(self._conversation_log, 1):
            agent_logger.info(f"\n--- Entry {idx} ---")
            agent_logger.info(f"{json.dumps(entry, indent=2, default=str)}")

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

        # The input for the first turn is empty (system prompt is in instructions).
        # For subsequent turns, input will contain tool results or user messages.
        next_input = []

        for turn in range(self.max_iterations):
            agent_logger.info(
                f"{'=' * 20} TURN {turn + 1}/{self.max_iterations} {'=' * 20}"
            )
            agent_logger.info("-" * 40)

            # Check if exploit.sh exists (reused by both nudges)
            exploit_exists = False
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
                exploit_exists = check_result.returncode == 0
            except Exception as e:
                agent_logger.warning(f"Failed to check exploit.sh: {e}")

            # Early nudge at ~20% — enforce "write exploit.sh" deadline
            early_nudge_turn = int(self.max_iterations * 0.2)
            if turn == early_nudge_turn and not exploit_exists:
                nudge_msg = (
                    f"PHASE CHECK: You have used {turn}/{self.max_iterations} turns. "
                    "You should be done reading code by now. Write your first draft of exploit.sh NOW, "
                    "even if imperfect. You can iterate and fix it. An imperfect exploit you can debug "
                    "is better than more code reading."
                )
                agent_logger.warning(nudge_msg)
                next_input.append(
                    {"type": "message", "role": "user", "content": nudge_msg}
                )

            # Later nudge at 60% — urgent if still no exploit
            nudge_turn = int(self.max_iterations * 0.6)
            if turn == nudge_turn and not exploit_exists:
                nudge_msg = (
                    f"URGENT: You have used {turn}/{self.max_iterations} turns (60%) and exploit.sh "
                    "still does not exist. STOP reading code. Re-read verify_exploit.sh, work backwards "
                    "from the success criteria, and write exploit.sh RIGHT NOW. You are running out of turns."
                )
                agent_logger.warning(nudge_msg)
                next_input.append(
                    {"type": "message", "role": "user", "content": nudge_msg}
                )

            # Add screenshot if enabled (currently unused).
            # TODO: Screenshots accumulate in server-side context via previous_response_id
            # every turn. The old Chat Completions code replaced the prior screenshot each
            # turn to bound context size. Needs a similar strategy before enabling.
            if self.screenshot_enabled:
                try:
                    screenshot_result = take_screenshot()
                    if screenshot_result.get("success"):
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

            # Determine the input for the API call
            # First turn: prompt agent to begin (instructions carry the system prompt)
            # Subsequent turns: use tool results / user messages
            if not next_input:
                call_input = (
                    "Begin. Read your instructions and start working."
                    if turn == 0
                    else "Continue."
                )
            else:
                call_input = next_input

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
                            input=call_input,
                            instructions=self._instructions,
                            previous_response_id=self._previous_response_id,
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
                self.token_tracker.record_from_openai_response(resp, model=self.model)
            except Exception as e:
                agent_logger.warning(f"Token tracking failed: {e}")

            # Store response ID for conversation continuity
            self._previous_response_id = resp.id

            # Extract output items from Responses API format
            output_items = getattr(resp, "output", [])

            # Parse output items: messages, function_calls, reasoning
            assistant_text = ""
            reasoning_summary = ""
            function_calls = []

            for item in output_items:
                item_type = getattr(item, "type", None)

                if item_type == "message":
                    content_blocks = getattr(item, "content", [])
                    for block in content_blocks:
                        if getattr(block, "type", None) == "output_text":
                            assistant_text += getattr(block, "text", "")
                elif item_type == "function_call":
                    function_calls.append(item)
                elif item_type == "reasoning":
                    for s in getattr(item, "summary", []) or []:
                        reasoning_summary += getattr(s, "text", "")

            # Log response
            tool_count = len(function_calls)
            agent_logger.info(
                f"[API RESPONSE - {len(assistant_text)} chars text, "
                f"{len(reasoning_summary)} chars reasoning, {tool_count} tool calls]"
            )

            if reasoning_summary:
                agent_logger.info(f"[REASONING SUMMARY] {reasoning_summary}")
            if assistant_text:
                agent_logger.info(f"[ASSISTANT TEXT] {assistant_text}")
            agent_logger.info("-" * 40)

            # Log to conversation archive
            self._conversation_log.append(
                {
                    "turn": turn + 1,
                    "response_id": resp.id,
                    "assistant_text": assistant_text,
                    "reasoning_summary": reasoning_summary,
                    "function_calls": [
                        {
                            "name": getattr(fc, "name", ""),
                            "call_id": getattr(fc, "call_id", ""),
                            "arguments": getattr(fc, "arguments", ""),
                        }
                        for fc in function_calls
                    ],
                }
            )

            # Process function calls (tool use)
            has_tool_call = bool(function_calls)

            # Prepare next_input for the next turn (tool results go here)
            next_input = []

            if function_calls:
                agent_logger.info(f"[TOOL CALLS DETECTED: {len(function_calls)}]")

                for fc in function_calls:
                    function_name = getattr(fc, "name", "")
                    arguments = getattr(fc, "arguments", "{}")
                    call_id = getattr(fc, "call_id", "")

                    agent_logger.info(f"Executing tool: {function_name}")
                    agent_logger.info(f"Arguments: {arguments}")

                    # Execute using local runtime
                    result = self.runtime.execute(function_name, arguments)

                    agent_logger.info(f"Result: {result}")

                    # Add tool result to next turn's input
                    next_input.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id,
                            "output": str(result),
                        }
                    )

            # Check for final submission command
            if assistant_text and assistant_text.strip():
                is_final_submission = False
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
                    next_input.append(
                        {
                            "type": "message",
                            "role": "user",
                            "content": warning_msg,
                        }
                    )
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
                        next_input.append(
                            {
                                "type": "message",
                                "role": "user",
                                "content": reminder_msg,
                            }
                        )
                        continue

                    # Exploit exists - proceed with submission
                    agent_logger.info(f"{'=' * 20} RUN COMPLETED {'=' * 20}")
                    agent_logger.info("Status: Final submission received")
                    agent_logger.info(f"Total turns: {turn + 1}")
                    agent_logger.info(f"Final message: {assistant_text}")
                    agent_logger.info(
                        f"Token totals: {json.dumps(self.token_tracker.totals())}"
                    )
                    agent_logger.info(f"Log file: {self.log_file}")

                    # Archive conversation before returning
                    self._archive_conversation()

                    return {
                        "status": "completed",
                        "turns": turn + 1,
                        "final_message": assistant_text,
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
