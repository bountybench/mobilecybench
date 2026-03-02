import json
import os
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv

from agent.agent_helpers import get_directory_tree
from agent.model_providers import get_model_provider
from agent.prompts.prompts import (
    LOOP_DETECTED_NUDGE,
    MISSING_OUTPUT_NUDGE,
    TURN_BUDGET_URGENT,
    TURN_BUDGET_WARNING,
    build_detect_prompt,
    build_synthetic_prompt,
)
from agent.tools.runtime import ToolRuntime
from utils.agent_utils import take_screenshot
from utils.logger import agent_logger, logger_manager
from utils.run_artifacts import jsonable, load_schema, utc_now_iso, validate_schema
from utils.time_tracker import time_tracker
from utils.token_tracker import TokenTracker

try:
    from jsonschema import validate as _jsonschema_validate
except Exception:
    _jsonschema_validate = None


class CustomAgent:
    OBSERVATION_MAX_CHARS = 8000

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

        agent_logger.info("Agent initialized with system prompt instructions.")

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
        self._tool_call_count = 0
        self._unique_tools = set()
        self._conversation_file = str(
            logger_manager.get_logs_dir() / "conversation.jsonl"
        )
        self._system_prompt_file = str(
            logger_manager.get_logs_dir() / "system_prompt.txt"
        )
        self._conversation_schema = self._load_conversation_schema()
        # Reset per-run structured conversation artifact.
        with open(self._conversation_file, "w", encoding="utf-8"):
            pass
        # Persist the full system prompt as a dedicated artifact for reproducibility.
        with open(self._system_prompt_file, "w", encoding="utf-8") as f:
            f.write(self._instructions)
            f.write("\n")

        agent_logger.info("Agent Run Started")
        agent_logger.info(f"Model: {self.model}")
        agent_logger.info(f"Max Iterations: {self.max_iterations}")
        agent_logger.info(f"System prompt artifact: {self._system_prompt_file}")
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
                    "/app/agent_exploit/exploit.sh",
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
            "agent_type": "custom",
            "status": "completed",
            "turns_taken": turns,
            "max_turns": self.max_iterations,
            "exploit_exists": exploit_exists,
            "final_message": final_message,
            "token_totals": self.token_tracker.totals(),
            "log_file": self.log_file,
            "conversation_file": self._conversation_file,
            "system_prompt_file": self._system_prompt_file,
            "tool_call_count": self._tool_call_count,
            "unique_tools": sorted(self._unique_tools),
        }

    def _format_observation_content(self, value):
        normalized = jsonable(value)
        if isinstance(normalized, str):
            if len(normalized) <= self.OBSERVATION_MAX_CHARS:
                return normalized, False
            return normalized[: self.OBSERVATION_MAX_CHARS] + "...[truncated]", True

        text = json.dumps(normalized, ensure_ascii=False)
        if len(text) <= self.OBSERVATION_MAX_CHARS:
            return text, False
        return text[: self.OBSERVATION_MAX_CHARS] + "...[truncated]", True

    def _append_turn_event(self, event):
        self._tool_call_count += len(event.get("tool_calls", []))
        for tool_call in event.get("tool_calls", []):
            tool_name = tool_call.get("name")
            if tool_name:
                self._unique_tools.add(tool_name)

        self._validate_turn_event(event)
        try:
            with open(self._conversation_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            agent_logger.warning(f"Failed to append conversation turn JSONL: {e}")

    def _load_conversation_schema(self):
        return load_schema(
            Path(__file__).parent.parent, "conversation_turn.schema.json"
        )

    def _validate_turn_event(self, event):
        validate_schema(event, self._conversation_schema, "conversation turn")

    def _parse_arguments(self, arguments: str) -> dict:
        """Safely parse tool arguments from JSON string."""
        try:
            if not arguments:
                return {}
            if isinstance(arguments, dict):
                return arguments
            return json.loads(arguments)
        except Exception:
            return {"raw": str(arguments)}

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

    @staticmethod
    def _commands_are_similar(cmd_a: str, cmd_b: str) -> bool:
        """Check if two commands are similar enough to count as a repeated attempt."""
        if not cmd_a or not cmd_b:
            return False
        # Exact match
        if cmd_a == cmd_b:
            return True
        # Same first line (e.g. same curl/python3 invocation with different args)
        first_a = cmd_a.split("\n")[0].strip()
        first_b = cmd_b.split("\n")[0].strip()
        if first_a == first_b:
            return True
        # Same tool target: extract first 2 whitespace-separated tokens
        tokens_a = first_a.split()[:2]
        tokens_b = first_b.split()[:2]
        if len(tokens_a) >= 2 and tokens_a == tokens_b:
            return True
        return False

    def run(self) -> dict:
        next_input = "Begin. Read your instructions and start working."

        # Track recent commands for loop detection: list of (command_str, had_error)
        recent_commands: list[tuple[str, bool]] = []

        # Compute turn budget thresholds
        warn_threshold = int(self.max_iterations * 0.66)
        urgent_threshold = int(self.max_iterations * 0.85)

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
                        # Rename the captured file for better organization within the turn
                        if "file_path" in screenshot_result:
                            try:
                                old_path = Path(screenshot_result["file_path"])
                                new_path = old_path.parent / f"turn_{turn + 1}.png"
                                old_path.rename(new_path)
                            except Exception:
                                pass

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
            turn_event = {
                "run_id": logger_manager.get_run_id(),
                "turn_number": turn + 1,
                "timestamp": utc_now_iso(),
                "role": "assistant",
                "response_id": resp.response_id,
                "assistant_text": assistant_text,
                "reasoning_summary": reasoning_summary,
                "tool_calls": [],
                "observations": [],
                "status": "ok",
            }

            # Prepare next_input for the next turn (tool results go here)
            next_input = []

            if function_calls:
                agent_logger.info(f"[TOOL CALLS DETECTED: {len(function_calls)}]")

                for fc in function_calls:
                    agent_logger.info(f"Executing tool: {fc.name}")
                    agent_logger.info(f"Arguments: {fc.arguments}")
                    turn_event["tool_calls"].append(
                        {
                            "tool_call_id": fc.call_id,
                            "name": fc.name,
                            "arguments": jsonable(self._parse_arguments(fc.arguments)),
                        }
                    )

                    # Execute using local runtime
                    try:
                        start_tool = time.perf_counter()
                        result = self.runtime.execute(fc.name, fc.arguments)
                        duration_tool = time.perf_counter() - start_tool
                    except Exception as e:
                        result = f"Error: {e}"
                        duration_tool = time.perf_counter() - start_tool
                        turn_event["status"] = "error"

                    agent_logger.info(f"Result: {result}")
                    obs_content, obs_truncated = self._format_observation_content(
                        result
                    )
                    if isinstance(result, str) and result.startswith("Error:"):
                        turn_event["status"] = "error"
                    turn_event["observations"].append(
                        {
                            "tool_call_id": fc.call_id,
                            "type": "tool_result",
                            "content": obs_content,
                            "truncated": obs_truncated,
                            "duration_seconds": round(duration_tool, 4),
                        }
                    )

                    # Add tool result to next turn's input
                    next_input.append(
                        {
                            "type": "function_call_output",
                            "call_id": fc.call_id,
                            "output": str(result),
                        }
                    )

                    # Track command for loop detection
                    cmd_str = ""
                    parsed_args = self._parse_arguments(fc.arguments)
                    if isinstance(parsed_args, dict):
                        cmd_str = parsed_args.get("command", "")
                    elif isinstance(parsed_args, str):
                        cmd_str = parsed_args
                    had_error = isinstance(result, str) and (
                        result.startswith("Error:")
                        or "error" in result[:200].lower()
                        or "not found" in result[:200].lower()
                    )
                    recent_commands.append((cmd_str, had_error))
                    # Keep only the last 5 entries
                    if len(recent_commands) > 5:
                        recent_commands = recent_commands[-5:]

            # Loop detection: check if last 3 commands are similar and all errored
            if len(recent_commands) >= 3:
                last3 = recent_commands[-3:]
                all_errored = all(err for _, err in last3)
                cmds_similar = (
                    self._commands_are_similar(last3[0][0], last3[1][0])
                    and self._commands_are_similar(last3[1][0], last3[2][0])
                )
                if all_errored and cmds_similar:
                    loop_msg = LOOP_DETECTED_NUDGE.format(count=3)
                    agent_logger.warning(loop_msg)
                    next_input.append(
                        {
                            "type": "message",
                            "role": "user",
                            "content": loop_msg,
                        }
                    )
                    turn_event["observations"].append(
                        {
                            "tool_call_id": None,
                            "type": "warning",
                            "content": loop_msg,
                            "truncated": False,
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
                    turn_event["observations"].append(
                        {
                            "tool_call_id": None,
                            "type": "warning",
                            "content": "FinalSubmissionCommand received but exploit.sh does not exist",
                            "truncated": False,
                        }
                    )
                    self._append_turn_event(turn_event)
                    next_input.append(
                        {
                            "type": "message",
                            "role": "user",
                            "content": (
                                "ERROR: You attempted to submit, but exploit.sh does not exist "
                                "at /app/agent_exploit/exploit.sh. Create it and submit again."
                            ),
                        }
                    )
                    continue

                self._append_turn_event(turn_event)
                return self._finish_run(
                    turns=turn + 1,
                    final_message=assistant_text,
                )

            # Nudge for missing text and/or tool calls
            has_text = bool(assistant_text and assistant_text.strip())
            missing = []
            if not has_text:
                missing.append(
                    "visible text in ANALYSIS/ACTION format"
                )
            if not has_tool_call:
                missing.append("a tool call")

            if missing:
                nudge_msg = MISSING_OUTPUT_NUDGE.format(
                    turn=turn + 1, missing=" and ".join(missing)
                )
                agent_logger.warning(nudge_msg)
                turn_event["observations"].append(
                    {
                        "tool_call_id": None,
                        "type": "warning",
                        "content": nudge_msg,
                        "truncated": False,
                    }
                )
                next_input.append(
                    {
                        "type": "message",
                        "role": "user",
                        "content": nudge_msg,
                    }
                )
                if not has_tool_call:
                    self._append_turn_event(turn_event)
                    continue  # Can't proceed without tool results

            # Turn budget reminders
            current_turn = turn + 1
            if current_turn == warn_threshold:
                remaining = self.max_iterations - current_turn
                budget_msg = TURN_BUDGET_WARNING.format(
                    used=current_turn,
                    total=self.max_iterations,
                    remaining=remaining,
                )
                agent_logger.info(budget_msg)
                next_input.append(
                    {
                        "type": "message",
                        "role": "user",
                        "content": budget_msg,
                    }
                )
            elif current_turn == urgent_threshold:
                remaining = self.max_iterations - current_turn
                budget_msg = TURN_BUDGET_URGENT.format(remaining=remaining)
                agent_logger.info(budget_msg)
                next_input.append(
                    {
                        "type": "message",
                        "role": "user",
                        "content": budget_msg,
                    }
                )

            self._append_turn_event(turn_event)

        # Ran out of turns
        return self._finish_run(turns=self.max_iterations)
