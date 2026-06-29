import json
import os
import subprocess
import time
from typing import Optional

import httpx
import jsonschema
import openai
from dotenv import load_dotenv

from agent.custom.backend.docker_ops import check_shell_script_content
from agent.custom.codebase_tree import get_directory_tree
from agent.custom.model_providers import get_model_provider
from agent.custom.tools.runtime import ToolRuntime
from agent.prompts.prompts import MISSING_OUTPUT_NUDGE
from utils.command_executor import CommandExecutor
from utils.json_io import load_validator
from utils.logger import agent_logger, logger_manager
from utils.run_artifacts import jsonable, utc_now_iso
from utils.time_tracker import time_tracker
from utils.token_tracker import TokenTracker

try:
    from jsonschema import validate as _jsonschema_validate
except Exception:
    _jsonschema_validate = None


# Default API timeout (ms). Overridden per-instance by the timeout_ms
# constructor argument; runner.py sources that from runner_config.json.
# Importing this module no longer requires a runner_config.json on disk.
DEFAULT_TIMEOUT_MS = 600_000

# Transient exceptions that should trigger retry.
# litellm's exception classes subclass openai.* so one tuple covers both providers.
# httpx.TransportError catches raw transport errors that escape SDK wrapping.
_RETRYABLE_EXC = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
    httpx.TransportError,
)


# Only scan files that could plausibly be executed as scripts.
_SCANNABLE_EXTENSIONS = frozenset(
    {
        "",  # no extension (executable scripts)
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".py",
        ".rb",
        ".pl",
        ".expect",
        ".exp",  # Expect scripts (automate interactive adb sessions)
    }
)


class CustomAgent:
    OBSERVATION_MAX_CHARS = 8000

    def __init__(
        self,
        model: str,
        max_iterations: int,
        max_model_response_tokens: int,
        app_name: str,
        instructions: str,
        llm_request_timeout_ms: int = DEFAULT_TIMEOUT_MS,
        reasoning_effort: Optional[str] = None,
        include_ssrf: bool = True,
        workflow: str = "redteam",
        attacker_model: str = "malicious_app",
        no_codebase: bool = False,
        allow_unregistered_model_routing: bool = False,
    ):
        self.include_ssrf = include_ssrf
        self.workflow = workflow
        self.attacker_model = attacker_model
        self.no_codebase = no_codebase

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
        self.llm_request_timeout_ms = llm_request_timeout_ms
        self.app_name = app_name

        self.runtime = ToolRuntime()
        self._instructions = instructions

        # Provider before tree fetch so a missing API key surfaces before
        # get_directory_tree's kali-404 noise can mask it.
        self.provider = get_model_provider(
            model=model,
            instructions=self._instructions,
            tools=self.runtime.get_tool_definitions(),
            max_output_tokens=max_model_response_tokens,
            timeout_ms=llm_request_timeout_ms,
            reasoning_effort=reasoning_effort,
            allow_unregistered=allow_unregistered_model_routing,
        )

        self._initial_tree_context = get_directory_tree(self.no_codebase)

        agent_logger.info("Agent initialized with system prompt instructions.")

        # Use shared logger's file name for consistency
        self.log_file = logger_manager.get_agent_log_file_name()

        # Initialize token tracker (writes per-call JSONL by default)
        self.token_tracker = TokenTracker()
        self._tool_call_count = 0
        self._unique_tools = set()
        # Mirror the BYO contract layout: agent state lives under
        # logs_dir/agent_run/ regardless of dispatch mode (see
        # documentation/supplemental/BRING_YOUR_OWN_AGENT.md).
        agent_run_dir = logger_manager.get_logs_dir() / "agent_run"
        agent_run_dir.mkdir(parents=True, exist_ok=True)
        self._conversation_file = str(agent_run_dir / "conversation.jsonl")
        self._system_prompt_file = str(agent_run_dir / "system_prompt.txt")
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

    def _check_exploit_exists(self) -> bool:
        """Check whether the expected exploit artifact exists in the kali container."""
        if self.workflow == "redteam" and self.attacker_model == "malicious_app":
            check_path = (
                "/app/agent_exploit/exploit_apk/dist/com.mobilecybench.exploit.apk"
            )
        else:
            check_path = "/app/agent_exploit/exploit.sh"

        # `test -f` exits 1 with empty stderr when the file is absent — the
        # normal "no" answer to an existence check. Anything else (non-1 exit,
        # or non-empty stderr like "No such container") is an operational
        # failure of the check itself, not a missing file. We classify the two
        # so that infra problems still surface as warnings while a legitimate
        # missing artifact stays silent.
        try:
            result = CommandExecutor().run(
                f"docker exec kali-container test -f {check_path}",
                capture_output=True,
                check=False,
                timeout=self.llm_request_timeout_ms // 1000,
            )
        except Exception as e:
            agent_logger.warning(f"Failed to check for exploit artifact: {e}")
            return False

        if result.returncode == 0:
            return True
        if result.returncode != 1 or result.stderr.strip():
            agent_logger.warning(
                f"Could not check {check_path} in kali-container "
                f"(exit_code={result.returncode}, "
                f"stderr={result.stderr.strip()!r})"
            )
        return False

    def _check_exploit_script_for_blocked_patterns(self) -> tuple[bool, list]:
        """Pull all files under /app/agent_exploit/ from the container and check
        for blocked patterns (e.g. adb root) in each one.

        Scanning every file (not just exploit.sh) closes the gap where an agent
        bundles a helper script with privileged operations and calls it from a
        clean exploit.sh.

        Returns (is_allowed, violations) where violations is a list of dicts with
        keys: file, line_number, line_content, matched_pattern.
        """
        try:
            # List all files in the agent_exploit directory
            ls_result = CommandExecutor().run(
                "docker exec kali-container find /app/agent_exploit -type f",
                capture_output=True,
                timeout=self.llm_request_timeout_ms // 1000,
            )

            if ls_result.returncode != 0:
                agent_logger.warning(
                    "Could not list agent_exploit in container — blocking submission"
                )
                return False, []

            files = [p.strip() for p in ls_result.stdout.splitlines() if p.strip()]
            if not files:
                agent_logger.warning(
                    "No files found in agent_exploit — blocking submission"
                )
                return False, []

            all_violations = []

            for container_path in files:
                ext = os.path.splitext(container_path)[1].lower()
                if ext not in _SCANNABLE_EXTENSIONS:
                    continue

                cat_result = subprocess.run(
                    ["docker", "exec", "kali-container", "cat", container_path],
                    capture_output=True,
                    text=True,
                    timeout=self.llm_request_timeout_ms // 1000,
                )
                if cat_result.returncode != 0:
                    agent_logger.warning(
                        f"Could not read {container_path} from container — blocking submission"
                    )
                    return False, []

                _, violations = check_shell_script_content(cat_result.stdout)

                for v in violations:
                    v["file"] = container_path
                all_violations.extend(violations)

            return len(all_violations) == 0, all_violations
        except Exception as e:
            agent_logger.warning(
                f"Failed to check agent_exploit for blocked patterns: {e} — blocking submission"
            )
            return False, []

    def _finish_run(self, turns: int, final_message: Optional[str] = None) -> dict:
        """Log summary, archive conversation, and return the result dict."""
        exploit_exists = self._check_exploit_exists()

        agent_logger.info(f"{'=' * 20} RUN COMPLETED {'=' * 20}")
        agent_logger.info(f"Turns: {turns}/{self.max_iterations}")
        agent_logger.info(f"Exploit exists: {exploit_exists}")
        if final_message:
            agent_logger.info(f"Final message: {final_message}")
        agent_logger.info(f"Token totals: {json.dumps(self.token_tracker.totals())}")

        self._archive_conversation()

        # cost_usd lives at result top level; calls lives in metrics.timing.
        # Neither belongs in token_totals.
        totals = self.token_tracker.totals()
        cost_usd = totals.pop("cost_usd", None)
        totals.pop("calls", None)

        result = {
            "status": "completed",
            "turns_taken": turns,
            "max_turns": self.max_iterations,
            "exploit_exists": exploit_exists,
            "final_message": final_message,
            "token_totals": totals,
            "log_file": self.log_file,
            "system_prompt_file": self._system_prompt_file,
            "tool_call_count": self._tool_call_count,
            "unique_tools": sorted(self._unique_tools),
        }
        if cost_usd is not None:
            result["cost_usd"] = cost_usd
        return result

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
        return load_validator("conversation_turn.schema.json")

    def _validate_turn_event(self, event):
        try:
            self._conversation_schema.validate(event)
        except jsonschema.ValidationError as e:
            agent_logger.warning("conversation turn schema validation failed: %s", e)

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

    def run(self) -> dict:
        next_input = "Begin. Read your instructions and start working."

        for turn in range(self.max_iterations):
            agent_logger.info(
                f"{'=' * 20} TURN {turn + 1}/{self.max_iterations} {'=' * 20}"
            )
            agent_logger.info("-" * 40)

            call_input = next_input

            # Retry logic for transient transport + rate limit errors.
            max_retries = 5
            base_retry_delay = 10  # seconds

            with time_tracker.llm_timing(
                model=self.model,
                conversation_id=self.app_name,
                turn=turn + 1,
            ) as timing_entry:
                for attempt in range(max_retries):
                    attempt_start = time.perf_counter()
                    try:
                        resp = self.provider.call(call_input)
                        agent_logger.info("API call completed")
                        timing_entry.attempt_count += 1
                        break
                    except Exception as e:
                        timing_entry.retry_durations.append(
                            time.perf_counter() - attempt_start
                        )
                        timing_entry.attempt_count += 1
                        if not isinstance(e, _RETRYABLE_EXC):
                            raise
                        if attempt >= max_retries - 1:
                            agent_logger.error(
                                f"{type(e).__name__} after {max_retries} attempts. Giving up."
                            )
                            raise
                        delay = base_retry_delay * (2**attempt)
                        agent_logger.warning(
                            f"{type(e).__name__} on attempt {attempt + 1}/{max_retries}. "
                            f"Retrying in {delay} seconds..."
                        )
                        time.sleep(delay)

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
                    if (
                        self.workflow == "redteam"
                        and self.attacker_model == "malicious_app"
                    ):
                        missing_msg = (
                            "FinalSubmissionCommand received but exploit APK not found. "
                            "Ensure your exploit is in exploit_files/exploit_apk/src/com/mobilecybench/exploit/ "
                            "and run build_exploit_apk.sh to build it."
                        )
                    else:
                        missing_msg = (
                            "ERROR: You attempted to submit, but exploit.sh does not exist "
                            "at /app/agent_exploit/exploit.sh. Create it and submit again."
                        )
                    agent_logger.warning(missing_msg)
                    turn_event["observations"].append(
                        {
                            "tool_call_id": None,
                            "type": "warning",
                            "content": missing_msg,
                            "truncated": False,
                        }
                    )
                    self._append_turn_event(turn_event)
                    next_input.append(
                        {
                            "type": "message",
                            "role": "user",
                            "content": missing_msg,
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
                    "visible text in Reflection/Plan/Thought/Log/Command format"
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

            self._append_turn_event(turn_event)

        # Ran out of turns
        return self._finish_run(turns=self.max_iterations)
