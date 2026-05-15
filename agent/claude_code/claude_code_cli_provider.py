#!/usr/bin/env python3

import json
import time
from typing import Any, Dict, List, Optional

import docker
from pydantic import BaseModel

from agent.claude_code.event_parser import ClaudeCodeEventParser
from utils.docker_utils import run_command_in_container
from utils.logger import logger


class ClaudeCodeCLIResult(BaseModel):
    """Result from a Claude Code CLI execution."""

    success: bool
    output_text: str
    tool_outputs: List[str]
    execution_time: float
    stderr: Optional[str] = None
    exit_code: int = -1
    turns: int = 0
    cost_usd: Optional[float] = None
    conversation_events: List[dict] = []
    session_id: Optional[str] = None
    result_payload: Optional[Dict[str, Any]] = None


class ClaudeCodeCLIProvider:
    """
    Claude Code CLI provider utilizing Docker SDK for robust streaming and execution.
    """

    def __init__(self):
        """Initialize the Claude Code CLI provider."""
        self.claude_binary = "claude"
        self.container_name = "kali-container"
        try:
            self.client = docker.from_env()
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            raise

    def validate(self) -> bool:
        """Validate that Claude Code CLI is available and authenticated."""
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
            exec_res = container.exec_run([self.claude_binary, "--version"])
            if exec_res.exit_code != 0:
                logger.error(
                    f"Claude Code CLI validation failed: {exec_res.output.decode()}"
                )
                return False
            logger.info(f"Claude Code CLI found: {exec_res.output.decode().strip()}")

            # Check authentication
            exec_res = container.exec_run(
                ["bash", "-c", f"{self.claude_binary} auth status"]
            )
            if exec_res.exit_code != 0:
                logger.error(
                    f"Claude Code auth check failed: {exec_res.output.decode()}"
                )
                return False

            output = exec_res.output.decode().strip()
            try:
                auth_status = json.loads(output)
                if not auth_status.get("loggedIn"):
                    logger.error("Claude Code is not authenticated")
                    return False
                logger.info(
                    f"Claude Code authenticated via {auth_status.get('authMethod')}"
                )
            except json.JSONDecodeError:
                logger.warning(f"Could not parse auth status: {output}")

            return True

        except Exception as e:
            logger.error(f"Unexpected error validating Claude Code CLI: {e}")
            return False

    def execute(
        self,
        prompt: str,
        timeout_ms: int = 1_200_000,
        model: str = "sonnet",
    ) -> ClaudeCodeCLIResult:
        """
        Execute Claude Code CLI in print mode with streaming JSON output.
        """
        start_time = time.time()
        timeout_sec = timeout_ms / 1000

        try:
            logger.info("Starting Claude Code execution")
            logger.info(f"Model: {model}")
            logger.info(f"Timeout: {timeout_ms}ms")

            # Build command
            # Permissions are pre-configured via ~/.claude/settings.json
            # (injected during container setup) to allow all tools without
            # prompting.  --dangerously-skip-permissions is NOT used because
            # it refuses to run as root.
            cmd = [
                "stdbuf",
                "-oL",
                "-eL",
                self.claude_binary,
                "-p",  # non-interactive print mode
                "--output-format",
                "stream-json",
                "--verbose",  # required for stream-json
                "--model",
                model,
                "--add-dir",
                "/",  # grant full filesystem access
                "--no-session-persistence",
                prompt,
            ]

            # Log the CLI flags (everything except the prompt, which is already
            # logged by the agent layer and can be very large).
            cli_flags = cmd[:-1]  # last element is the prompt text
            logger.info(
                f"Executing in container: {' '.join(cli_flags)} <prompt: {len(prompt)} chars>"
            )

            parser = ClaudeCodeEventParser()

            def handle_stderr(text: str):
                for line in text.splitlines():
                    line = line.strip()
                    if line:
                        logger.warning(f"[ClaudeCode stderr] {line}")

            _, stderr_text, exit_code = run_command_in_container(
                self.container_name,
                cmd,
                timeout_sec,
                stdout_callback=parser.feed_chunk,
                stderr_callback=handle_stderr,
            )

            parser.flush()

            total_time = time.time() - start_time
            logger.info(f"Completed Claude Code execution in {total_time:.1f}s")
            logger.info(f"Exit code: {exit_code}")
            logger.info(f"Output length: {len(parser.final_output)} chars")
            if stderr_text:
                logger.warning(f"Stderr: {stderr_text}")

            return ClaudeCodeCLIResult(
                success=(exit_code == 0),
                output_text=parser.final_output,
                tool_outputs=parser.tool_outputs,
                execution_time=total_time,
                stderr=stderr_text,
                exit_code=exit_code,
                turns=parser.result_turns,
                cost_usd=parser.result_cost,
                conversation_events=parser.conversation_events,
                session_id=parser.session_id,
                result_payload=parser.result_payload,
            )

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Claude Code execution failed: {e}", exc_info=True)
            return ClaudeCodeCLIResult(
                success=False,
                output_text="",
                tool_outputs=[],
                execution_time=execution_time,
                stderr=str(e),
            )
