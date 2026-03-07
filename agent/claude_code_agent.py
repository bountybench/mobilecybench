"""Claude Code agent — delegates multi-turn execution to the Claude Code CLI."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from agent.agent_helpers import get_directory_tree
from agent.claude_code.claude_code_cli_provider import ClaudeCodeCLIProvider
from agent.prompts.prompts import build_detect_prompt, build_synthetic_prompt
from utils.logger import agent_logger, logger_manager
from utils.run_artifacts import load_schema, utc_now_iso, validate_schema


class ClaudeCodeAgent:
    """Thin wrapper around the Claude Code CLI.

    Unlike :class:`CustomAgent` which owns the turn loop and calls a
    model-provider per turn, this agent delegates the entire agentic loop
    to the ``claude`` CLI running inside the kali container.  The CLI
    streams JSON events that we parse into the same ``conversation.jsonl``
    format used by the custom agent.
    """

    def __init__(
        self,
        model: str,
        timeout_ms: int,
        app_name: str = "",
        app_server: Optional[str] = None,
        package_name: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        include_ssrf: bool = True,
        workflow: str = "discovery",
    ):
        """Initialise the Claude Code agent.

        Args:
            model: Claude model to use (e.g. "sonnet", "opus", "haiku").
            timeout_ms: Timeout for the CLI execution in milliseconds.
            app_name: Name of the app under test.
            app_server: Optional backend server URL.
            package_name: Android package name.
            username: App credentials.
            password: App credentials.
            include_ssrf: Whether to include SSRF instructions.
            workflow: ``"discovery"`` or ``"exploit"``.
        """
        self.app_name = app_name
        self.app_server = app_server
        self.timeout_ms = timeout_ms
        self.package_name = package_name
        self.username = username
        self.password = password
        self.include_ssrf = include_ssrf
        self.model = model
        self.workflow = workflow

        # Load .env from the agent directory (same pattern as CustomAgent)
        agent_dir = os.path.dirname(os.path.abspath(__file__))
        env_file = os.path.join(agent_dir, ".env")
        if os.path.exists(env_file):
            load_dotenv(env_file, override=True)

        # Build system prompt (mirrors CustomAgent._get_system_prompt_text)
        self._initial_tree_context = get_directory_tree()
        self._instructions = self._get_system_prompt_text()

        # Provider handles CLI execution inside the kali container
        self.provider = ClaudeCodeCLIProvider()

        # Logging & artifact paths (shared with runner logger infrastructure)
        self.log_file = logger_manager.get_agent_log_file_name()
        self._logs_dir = Path(logger_manager.get_logs_dir())
        self._conversation_file = str(self._logs_dir / "conversation.jsonl")
        self._system_prompt_file = str(self._logs_dir / "system_prompt.txt")
        self._conversation_schema = load_schema(
            Path(__file__).parent.parent, "conversation_turn.schema.json"
        )

        # Tracking (populated after CLI execution)
        self._tool_call_count = 0
        self._unique_tools: set = set()

        # Reset conversation artifact
        with open(self._conversation_file, "w", encoding="utf-8"):
            pass
        # Persist system prompt for reproducibility
        with open(self._system_prompt_file, "w", encoding="utf-8") as f:
            f.write(self._instructions)
            f.write("\n")

        agent_logger.info("Agent Run Started")
        agent_logger.info("Agent: claude-code")
        agent_logger.info(f"Model: {self.model}")
        agent_logger.info(f"App: {self.app_name}")
        agent_logger.info(f"Workflow: {self.workflow}")
        agent_logger.info(f"System prompt artifact: {self._system_prompt_file}")
        agent_logger.info(f"System prompt:\n{self._instructions}")
        agent_logger.info("=" * 80)

    # ------------------------------------------------------------------
    # Prompt building (identical logic to CustomAgent._get_system_prompt_text)
    # ------------------------------------------------------------------

    def _get_system_prompt_text(self) -> str:
        """Build the system prompt based on workflow mode."""
        if self.workflow == "exploit":
            # TODO: Evaluate whether the Claude Code CLI needs additional
            # exploit-mode guidance beyond the standard synthetic prompt
            # (e.g. explicit instructions to write exploit.sh, or special
            # handling for verify_files).
            return build_synthetic_prompt(
                package_name=self.package_name,
                username=self.username,
                password=self.password,
                app_server=self.app_server,
            )

        return build_detect_prompt(
            package_name=self.package_name,
            codebase_tree=self._initial_tree_context,
            app_server=self.app_server,
            username=self.username,
            password=self.password,
            include_ssrf=self.include_ssrf,
        )

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        """Execute the Claude Code CLI and return a result dict.

        The result dict uses the same keys as
        :meth:`CustomAgent._finish_run` so that ``run_artifacts.py`` can
        process it uniformly.
        """
        agent_logger.info("Starting Claude Code CLI execution...")

        if not self.provider.validate():
            raise RuntimeError(
                "Claude Code CLI validation failed. "
                "Ensure the kali container is running, claude is installed, "
                "and OAuth tokens are configured in agent/.env."
            )

        try:
            result = self.provider.execute(
                prompt=self._instructions,
                timeout_ms=self.timeout_ms,
                model=self.model,
            )

            # Ingest CLI conversation events into our standard JSONL format
            self._ingest_conversation_events(result.conversation_events)

            # The CLI's `result` event carries `num_turns`, but on timeout
            # the event is never emitted so result.turns stays 0.  Fall
            # back to the number of conversation events we actually parsed.
            effective_turns = result.turns or len(result.conversation_events)

            if not result.success:
                # Distinguish timeout (exit_code == -1) from real errors
                is_timeout = result.exit_code == -1
                status = "timeout" if is_timeout else "error"
                msg = result.stderr or (
                    "CLI timed out" if is_timeout else "unknown error"
                )
                agent_logger.error(f"Claude Code execution {status}: {msg}")
                return self._finish_run(
                    turns=effective_turns,
                    status=status,
                    final_message=msg,
                    cost_usd=result.cost_usd,
                )

            return self._finish_run(
                turns=effective_turns,
                status="completed",
                final_message=result.output_text,
                cost_usd=result.cost_usd,
            )

        except Exception as e:
            agent_logger.error(f"Claude Code execution failed: {e}")
            return self._finish_run(turns=0, status="error", final_message=str(e))

    # ------------------------------------------------------------------
    # Conversation tracking (mirrors CustomAgent._append_turn_event)
    # ------------------------------------------------------------------

    def _ingest_conversation_events(self, events: list) -> None:
        """Convert CLI conversation events to schema-validated turn events."""
        run_id = logger_manager.get_run_id()

        for event in events:
            turn_number = event.get("turn", 0)
            tool_calls = event.get("tool_calls", [])
            observations = event.get("observations", [])

            # Normalise tool_calls to match conversation_turn schema
            normalised_tool_calls = []
            for tc in tool_calls:
                tool_name = tc.get("name", "unknown")
                self._unique_tools.add(tool_name)
                normalised_tool_calls.append(
                    {
                        "tool_call_id": tc.get("tool_call_id", ""),
                        "name": tool_name,
                        "arguments": tc.get("arguments", {}),
                    }
                )
            self._tool_call_count += len(normalised_tool_calls)

            # Normalise observations
            normalised_obs = []
            for obs in observations:
                normalised_obs.append(
                    {
                        "tool_call_id": obs.get("tool_use_id", obs.get("tool_call_id")),
                        "type": "tool_result",
                        "content": obs.get("content", ""),
                        "truncated": False,
                    }
                )

            turn_event = {
                "run_id": run_id,
                "turn_number": turn_number,
                "timestamp": utc_now_iso(),
                "role": "assistant",
                "response_id": None,
                "assistant_text": event.get("assistant_text", ""),
                "reasoning_summary": "",
                "tool_calls": normalised_tool_calls,
                "observations": normalised_obs,
                "status": "ok",
            }

            self._append_turn_event(turn_event)

    def _append_turn_event(self, event: dict) -> None:
        """Validate and append a turn event to conversation.jsonl."""
        validate_schema(event, self._conversation_schema, "conversation turn")
        try:
            with open(self._conversation_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            agent_logger.warning(f"Failed to append conversation turn JSONL: {e}")

    # ------------------------------------------------------------------
    # Exploit check (same as CustomAgent._check_exploit_exists)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Result (mirrors CustomAgent._finish_run)
    # ------------------------------------------------------------------

    def _finish_run(
        self,
        turns: int,
        status: str = "completed",
        final_message: Optional[str] = None,
        cost_usd: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Build result dict compatible with run_artifacts.normalize_agent_result."""
        exploit_exists = self._check_exploit_exists()

        agent_logger.info(f"{'=' * 20} RUN COMPLETED {'=' * 20}")
        agent_logger.info(f"Turns: {turns}")
        agent_logger.info(f"Exploit exists: {exploit_exists}")
        if cost_usd is not None:
            agent_logger.info(f"Cost: ${cost_usd:.4f}")
        if final_message:
            agent_logger.info(f"Final message: {final_message}")

        return {
            "agent_type": "claude-code",
            "status": status,
            "turns_taken": turns,
            "max_turns": 0,  # CLI manages its own turn limit
            "exploit_exists": exploit_exists,
            "final_message": final_message,
            "token_totals": {},  # CLI doesn't expose per-token counts
            "cost_usd": cost_usd,
            "log_file": self.log_file,
            "conversation_file": self._conversation_file,
            "system_prompt_file": self._system_prompt_file,
            "tool_call_count": self._tool_call_count,
            "unique_tools": sorted(self._unique_tools),
        }
