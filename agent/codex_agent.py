"""Codex agent — delegates multi-turn execution to the Codex CLI."""

import json
import os
import signal
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from agent.agent_helpers import get_directory_tree
from agent.codex.codex_cli_provider import CodexCLIProvider
from agent.prompts.prompts import (
    build_malicious_app_prompt,
    build_remote_attacker_prompt,
    build_synthetic_prompt,
)
from utils.logger import agent_logger, logger, logger_manager
from utils.run_artifacts import load_schema, utc_now_iso, validate_schema


class CodexAgent:
    """Thin wrapper around the Codex CLI.

    Delegates the entire agentic loop to the ``codex`` CLI running inside
    the kali container.  The CLI streams JSON events that we parse into
    the same ``conversation.jsonl`` format used by the claude-code agent.
    """

    def __init__(
        self,
        app_name: str = "",
        dry_run: bool = False,
        app_server: Optional[str] = None,
        emulator_server: Optional[str] = None,
        timeout_ms: int = 1_200_000,
        package_name: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        include_ssrf: bool = True,
        workflow: str = "exploit",
        attacker_model: str = "malicious_app",
        additional_context: Optional[str] = None,
        no_codebase: bool = False,
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        vuln_id: str = "vuln_0",
    ):
        self.app_name = app_name
        self.dry_run = dry_run
        self.app_server = app_server
        self.emulator_server = emulator_server
        self.timeout_ms = timeout_ms
        self.package_name = package_name
        self.username = username
        self.password = password
        self.include_ssrf = include_ssrf
        self.workflow = workflow
        self.attacker_model = attacker_model
        self.additional_context = additional_context
        self.no_codebase = no_codebase
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.vuln_id = vuln_id

        # Load environment variables
        agent_dir = os.path.dirname(os.path.abspath(__file__))
        env_file = os.path.join(agent_dir, ".env")
        if os.path.exists(env_file):
            load_dotenv(env_file, override=True)

        # Build system prompt
        self._initial_tree_context = get_directory_tree(self.no_codebase)
        self._instructions = self._get_system_prompt_text()

        # Provider handles CLI execution inside the kali container
        self.provider = CodexCLIProvider()

        # Set up signal handler for graceful cleanup on Ctrl-C
        signal.signal(signal.SIGINT, self._signal_handler)

        # Validate provider unless in dry run mode
        if not dry_run:
            if not self.provider.validate():
                raise RuntimeError(
                    "Codex CLI validation failed. Please ensure Codex CLI is installed and accessible."
                )

        # Logging & artifact paths
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
        agent_logger.info("Agent: codex")
        agent_logger.info(f"App: {self.app_name}")
        agent_logger.info(f"Workflow: {self.workflow}")
        agent_logger.info(f"System prompt artifact: {self._system_prompt_file}")
        agent_logger.info(f"System prompt:\n{self._instructions}")
        agent_logger.info("=" * 80)

    # ------------------------------------------------------------------
    # Prompt building (identical to ClaudeCodeAgent)
    # ------------------------------------------------------------------

    def _get_system_prompt_text(self) -> str:
        """Build the system prompt based on workflow mode."""
        if self.workflow == "redteam":
            builder = (
                build_remote_attacker_prompt
                if self.attacker_model == "remote_attacker"
                else build_malicious_app_prompt
            )
            prompt = builder(
                package_name=self.package_name,
                app_server=self.app_server,
                emulator_server=self.emulator_server,
                username=self.username,
                password=self.password,
                no_codebase=self.no_codebase,
                agent_type="codex",
            )
        else:
            prompt = build_synthetic_prompt(
                package_name=self.package_name,
                username=self.username,
                password=self.password,
                app_server=self.app_server,
                emulator_server=self.emulator_server,
                no_codebase=self.no_codebase,
                agent_type="codex",
                vuln_id=self.vuln_id,
            )

        if self.additional_context:
            prompt = prompt + "\n\n" + self.additional_context

        return prompt

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        """Execute the Codex CLI and return a result dict."""
        agent_logger.info("Starting Codex CLI execution...")

        if self.dry_run:
            logger.info("DRY RUN MODE - No actual Codex CLI execution")
            return self._finish_run(turns=0, status="dry_run_completed")

        codex_config: Dict[str, Any] = {}
        if self.model:
            codex_config["model"] = self.model
        if self.reasoning_effort:
            codex_config["model_reasoning_effort"] = self.reasoning_effort

        try:
            result = self.provider.execute(
                prompt=self._instructions,
                timeout_ms=self.timeout_ms,
                codex_config=codex_config or None,
                no_codebase=self.no_codebase,
            )

            # Ingest CLI conversation events into our standard JSONL format
            self._ingest_conversation_events(result.conversation_events)

            # Fall back to number of conversation events if turns is 0
            effective_turns = result.turns or len(result.conversation_events)

            # Build token totals + request/latency metrics from provider data.
            token_totals = self._build_token_totals(result)
            timing_summary = self._build_timing_summary(result)

            if not result.success:
                is_timeout = result.exit_code == -1
                status = "timeout" if is_timeout else "error"
                parts = []
                if is_timeout:
                    parts.append(f"CLI timed out after {self.timeout_ms / 1000:.0f}s")
                else:
                    parts.append(f"CLI exited with code {result.exit_code}")
                if result.stderr:
                    parts.append(f"stderr: {result.stderr}")
                msg = " | ".join(parts)
                if is_timeout:
                    agent_logger.info(f"Codex execution {status}: {msg}")
                    logger.info(f"Codex execution {status}: {msg}")
                else:
                    agent_logger.error(f"Codex execution {status}: {msg}")
                    logger.error(f"Codex execution {status}: {msg}")
                return self._finish_run(
                    turns=effective_turns,
                    status=status,
                    final_message=msg,
                    token_totals=token_totals,
                    timing=timing_summary,
                )

            return self._finish_run(
                turns=effective_turns,
                status="completed",
                final_message=result.output_text,
                token_totals=token_totals,
                timing=timing_summary,
            )

        except Exception as e:
            agent_logger.error(f"Codex execution failed: {e}", exc_info=True)
            logger.error(f"Codex execution failed: {e}", exc_info=True)
            return self._finish_run(turns=0, status="error", final_message=str(e))

    # ------------------------------------------------------------------
    # Conversation tracking (mirrors ClaudeCodeAgent)
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
                        "tool_call_id": obs.get("tool_call_id", ""),
                        "type": "tool_result",
                        "content": obs.get("content", ""),
                        "truncated": obs.get("truncated", False),
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
    # Exploit check (same as ClaudeCodeAgent)
    # ------------------------------------------------------------------

    def _check_exploit_exists(self) -> bool:
        """Check whether the expected exploit artifact exists in the kali container."""
        if self.workflow == "redteam" and self.attacker_model == "malicious_app":
            check_path = (
                "/app/agent_exploit/exploit_apk/dist/com.mobilecybench.exploit.apk"
            )
        else:
            check_path = "/app/agent_exploit/exploit.sh"
        try:
            container = self.provider.client.containers.get(
                self.provider.container_name
            )
            result = container.exec_run(["test", "-f", check_path])
            return result.exit_code == 0
        except Exception as e:
            agent_logger.warning(f"Failed to check for exploit artifact: {e}")
            return False

    # ------------------------------------------------------------------
    # Result (mirrors ClaudeCodeAgent._finish_run)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_token_totals(result) -> Dict[str, Any]:
        """Flatten provider usage + per-request metadata into token_totals."""
        totals: Dict[str, Any] = {}
        if result.token_usage:
            totals.update(result.token_usage)

        # Per-request and model context
        totals["num_requests"] = len(result.turn_durations) or int(result.turns or 0)
        totals["failed_requests"] = int(result.failed_turns or 0)
        if result.configured_model:
            totals["model"] = result.configured_model
            # Mirrors Claude Code's per_model shape so downstream tooling can
            # handle both uniformly.  Codex currently reports a single model
            # per run (the configured one), so the list has one entry.
            totals["models_used"] = [result.configured_model]
        if result.thread_id:
            totals["thread_id"] = result.thread_id
        if result.per_turn_usage:
            totals["per_request_usage"] = result.per_turn_usage
        if result.tool_call_breakdown:
            totals["tool_call_breakdown"] = dict(result.tool_call_breakdown)
        if result.shell_exit_codes:
            totals["shell_exit_codes"] = list(result.shell_exit_codes)
            totals["shell_failure_count"] = sum(
                1 for c in result.shell_exit_codes if c != 0
            )
        return totals

    @staticmethod
    def _build_timing_summary(result) -> Dict[str, Any]:
        """Derive latency stats from per-turn wall-clock durations."""
        durations = list(result.turn_durations or [])
        summary: Dict[str, Any] = {
            "total_execution_time": float(result.execution_time or 0.0),
            "llm_call_count": len(durations),
        }
        if not durations:
            summary.update(
                {
                    "total_llm_time": 0.0,
                    "mean": None,
                    "p50": None,
                    "p95": None,
                    "min": None,
                    "max": None,
                    "per_request_durations": [],
                }
            )
            return summary

        ordered = sorted(durations)
        n = len(ordered)
        summary.update(
            {
                "total_llm_time": float(sum(ordered)),
                "mean": float(sum(ordered) / n),
                "p50": float(ordered[n // 2]),
                "p95": float(ordered[min(int(n * 0.95), n - 1)]),
                "min": float(ordered[0]),
                "max": float(ordered[-1]),
                "per_request_durations": [float(d) for d in durations],
            }
        )
        return summary

    def _finish_run(
        self,
        turns: int,
        status: str = "completed",
        final_message: Optional[str] = None,
        token_totals: Optional[Dict[str, Any]] = None,
        timing: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build result dict compatible with run_artifacts.normalize_agent_result."""
        exploit_exists = self._check_exploit_exists()

        agent_logger.info(f"{'=' * 20} RUN COMPLETED {'=' * 20}")
        agent_logger.info(f"Turns: {turns}")
        agent_logger.info(f"Exploit exists: {exploit_exists}")
        if timing and timing.get("llm_call_count"):
            agent_logger.info(
                "Model requests: %s | total=%0.1fs | mean=%0.1fs | p95=%0.1fs | max=%0.1fs",
                timing.get("llm_call_count"),
                timing.get("total_llm_time") or 0.0,
                timing.get("mean") or 0.0,
                timing.get("p95") or 0.0,
                timing.get("max") or 0.0,
            )
        if token_totals and token_totals.get("model"):
            agent_logger.info(f"Model: {token_totals['model']}")
        if final_message:
            agent_logger.info(f"Final message: {final_message}")

        return {
            "agent_type": "codex",
            "status": status,
            "turns_taken": turns,
            "max_turns": 0,  # CLI manages its own turn limit
            "exploit_exists": exploit_exists,
            "final_message": final_message,
            "token_totals": token_totals or {},
            "timing": timing or {},
            "log_file": self.log_file,
            "conversation_file": self._conversation_file,
            "system_prompt_file": self._system_prompt_file,
            "tool_call_count": self._tool_call_count,
            "unique_tools": sorted(self._unique_tools),
        }

    def _signal_handler(self, _sig, _frame):
        """Handle Ctrl-C (SIGINT) for graceful cleanup."""
        logger.info("\nCtrl-C received, exiting...")
        sys.exit(0)
