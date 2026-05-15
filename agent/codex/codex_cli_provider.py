#!/usr/bin/env python3

import time
from typing import Any, Dict, List, Optional

import docker
from pydantic import BaseModel

from agent.codex.event_parser import CodexEventParser
from utils.docker_utils import run_command_in_container
from utils.logger import logger


class CodexCLIResult(BaseModel):
    """Result from a Codex CLI execution."""

    success: bool
    output_text: str
    tool_outputs: List[str]
    execution_time: float
    stderr: Optional[str] = None
    exit_code: int = -1
    turns: int = 0
    conversation_events: List[Dict[str, Any]] = []
    token_usage: Dict[str, int] = {}
    thread_id: Optional[str] = None
    # Per-turn wall-clock durations, in seconds, measured from turn.started
    # to turn.completed (one entry per successfully completed model request).
    turn_durations: List[float] = []
    # Raw usage payload emitted on each turn.completed event, in order.
    per_turn_usage: List[Dict[str, Any]] = []
    # Number of turn.failed events seen (request-level failures).
    failed_turns: int = 0
    # Tool invocation breakdown by tool name.
    tool_call_breakdown: Dict[str, int] = {}
    # Exit codes from every command_execution item we saw.
    shell_exit_codes: List[int] = []
    # Configured model for this run (codex --json does not yet report
    # per-turn model; track what we asked for until it does).
    configured_model: Optional[str] = None


class CodexCLIProvider:
    """
    Codex CLI provider utilizing Docker SDK for robust streaming and execution.
    """

    def __init__(self):
        """
        Initialize the Codex CLI provider.
        """
        self.codex_binary = "codex"
        self.container_name = "kali-container"
        try:
            self.client = docker.from_env()
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            raise

    def validate(self) -> bool:
        """Validate that Codex CLI is available and accessible."""
        try:
            # Check if container is running
            try:
                container = self.client.containers.get(self.container_name)
                if container.status != "running":
                    logger.error(f"Container {self.container_name} is not running")
                    return False
            except docker.errors.NotFound:
                logger.error(f"Container {self.container_name} not found")
                return False

            # Check binary
            exec_res = container.exec_run([self.codex_binary, "--version"])
            if exec_res.exit_code == 0:
                logger.info(
                    f"Codex CLI binary found: {exec_res.output.decode().strip()}"
                )
                return True
            else:
                logger.error(f"Codex CLI validation failed: {exec_res.output.decode()}")
                return False

        except Exception as e:
            logger.error(f"Unexpected error validating Codex CLI: {e}")
            return False

    def execute(
        self,
        prompt: str,
        timeout_ms: int = 1_200_000,
        codex_config: Optional[dict] = None,
        no_codebase: bool = False,
    ) -> CodexCLIResult:
        """
        Execute Codex CLI in single-iteration mode (no session resumption).
        """
        start_time = time.time()
        timeout_sec = timeout_ms / 1000

        try:
            # When no_codebase is set, agent_container mounts the APK at
            # /app/apk and does not bind /app/codebase into the agent's view.
            app_codebase_dir = "/app/apk" if no_codebase else "/app/codebase"

            logger.info("🚀 Starting Codex execution (single iteration)")
            logger.info(f"Working directory: {app_codebase_dir}")
            logger.info(f"Timeout: {timeout_ms}ms")

            # Default headless configuration
            config = {
                "history.persistence": "none",
                "tui.animations": False,
                "tui.notifications": False,
                "approval_policy": "never",
                "sandbox_mode": "danger-full-access",
                "model_reasoning_effort": "high",
                "model": "gpt-5.4",
                "model_reasoning_summary": "detailed",
                "model_verbosity": "high",
            }
            if codex_config:
                config.update(codex_config)

            # Construct command
            # stdbuf is used to force line buffering
            cmd = [
                "stdbuf",
                "-oL",
                "-eL",
                self.codex_binary,
            ]

            # Append configuration flags (Global options must precede subcommand)
            for key, val in config.items():
                if isinstance(val, bool):
                    toml_val = "true" if val else "false"
                elif isinstance(val, str):
                    toml_val = f"'{val}'"  # Quote strings for TOML
                else:
                    toml_val = str(val)
                cmd.extend(["--config", f"{key}={toml_val}"])

            # Append subcommand and its flags
            cmd.extend(
                [
                    "exec",
                    "--dangerously-bypass-approvals-and-sandbox",
                    "--skip-git-repo-check",
                    "--json",
                    "-C",
                    app_codebase_dir,
                    prompt,
                ]
            )

            logger.info(f"Executing in container: {' '.join(cmd)}")

            configured_model: Optional[str] = None
            if codex_config:
                maybe_model = codex_config.get("model")
                if isinstance(maybe_model, str):
                    configured_model = maybe_model
            if configured_model is None:
                maybe_default_model = config.get("model")
                if isinstance(maybe_default_model, str):
                    configured_model = maybe_default_model

            parser = CodexEventParser()

            # Execute using helper; parser.feed_chunk consumes JSONL lines.
            _, stderr_text, exit_code = run_command_in_container(
                self.container_name,
                cmd,
                timeout_sec,
                stdout_callback=parser.feed_chunk,
            )

            # Drain any partial line + in-flight turn at stream end.
            parser.flush()

            total_time = time.time() - start_time
            logger.info(f"🏁 Completed execution in {total_time:.1f}s")
            logger.info(f"Output length: {len(parser.final_output)} chars")
            if parser.turn_durations:
                mean_dur = sum(parser.turn_durations) / len(parser.turn_durations)
                logger.info(
                    f"[Codex] {len(parser.turn_durations)} model requests, "
                    f"total={sum(parser.turn_durations):.1f}s, "
                    f"mean={mean_dur:.1f}s, max={max(parser.turn_durations):.1f}s"
                )

            return CodexCLIResult(
                success=(exit_code == 0),
                output_text=parser.final_output,
                tool_outputs=parser.tool_outputs,
                execution_time=total_time,
                stderr=stderr_text,
                exit_code=exit_code,
                turns=parser.turn_count,
                conversation_events=parser.conversation_events,
                token_usage=parser.token_usage,
                thread_id=parser.thread_id,
                turn_durations=parser.turn_durations,
                per_turn_usage=parser.per_turn_usage,
                failed_turns=parser.failed_turns,
                tool_call_breakdown=parser.tool_call_breakdown,
                shell_exit_codes=parser.shell_exit_codes,
                configured_model=configured_model,
            )

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Codex execution failed: {e}")
            return CodexCLIResult(
                success=False,
                output_text="",
                tool_outputs=[],
                execution_time=execution_time,
                stderr=str(e),
            )
