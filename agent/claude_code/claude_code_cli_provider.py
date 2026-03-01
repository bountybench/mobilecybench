#!/usr/bin/env python3

import json
import time
from typing import List, Optional

import docker
from pydantic import BaseModel

from utils.docker_utils import run_command_in_container
from utils.logger import agent_logger, logger


class ClaudeCodeCLIResult(BaseModel):
    """Result from a Claude Code CLI execution."""

    success: bool
    output_text: str
    tool_outputs: List[str]
    execution_time: float
    stderr: Optional[str] = None
    turns: int = 0
    cost_usd: Optional[float] = None


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

            logger.info(f"Executing in container: {' '.join(cmd[:10])}...")

            # State for callbacks
            tool_outputs = []
            assistant_messages = []
            result_turns = 0
            result_cost = None

            def parse_output_chunk(text: str):
                """Parse JSONL chunks from stdout."""
                nonlocal result_turns, result_cost

                for line in text.strip().split("\n"):
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        event_type = data.get("type")

                        if event_type == "system":
                            subtype = data.get("subtype")
                            if subtype == "init":
                                session_id = data.get("session_id", "unknown")
                                logger.info(
                                    f"[ClaudeCode] Session started: {session_id}"
                                )

                        elif event_type == "assistant":
                            message = data.get("message", {})
                            for content in message.get("content", []):
                                content_type = content.get("type")
                                if content_type == "text":
                                    text_content = content.get("text", "")
                                    if text_content:
                                        assistant_messages.append(text_content)
                                        preview = (
                                            (text_content[:200] + "...")
                                            if len(text_content) > 200
                                            else text_content
                                        )
                                        logger.info(f"[ClaudeCode Message] {preview}")
                                elif content_type == "tool_use":
                                    tool_name = content.get("name", "unknown")
                                    logger.info(f"[ClaudeCode Tool] {tool_name}")
                                    agent_logger.info("tool_use name=%s", tool_name)

                        elif event_type == "user":
                            message = data.get("message", {})
                            for content in message.get("content", []):
                                if content.get("type") == "tool_result":
                                    tool_outputs.append(json.dumps(content))
                                    agent_logger.info(
                                        "tool_result has_content=%s",
                                        bool(content.get("content")),
                                    )

                        elif event_type == "result":
                            result_turns = data.get("num_turns", 0)
                            result_cost = data.get("total_cost_usd")
                            subtype = data.get("subtype")
                            if subtype == "success":
                                logger.info(
                                    f"[ClaudeCode] Completed: "
                                    f"{result_turns} turns, "
                                    f"${result_cost:.4f}"
                                    if result_cost
                                    else f"[ClaudeCode] Completed: "
                                    f"{result_turns} turns"
                                )
                            elif subtype == "error":
                                logger.error(f"[ClaudeCode] Error: {data.get('error')}")

                    except json.JSONDecodeError:
                        # Raw output (not JSON)
                        if line.strip():
                            logger.info(f"[ClaudeCode Raw] {line.strip()}")

            # Execute using shared helper
            _, stderr_text, exit_code = run_command_in_container(
                self.container_name,
                cmd,
                timeout_sec,
                stdout_callback=parse_output_chunk,
            )

            final_output = "\n".join(assistant_messages)

            total_time = time.time() - start_time
            logger.info(f"Completed Claude Code execution in {total_time:.1f}s")
            logger.info(f"Output length: {len(final_output)} chars")

            return ClaudeCodeCLIResult(
                success=(exit_code == 0),
                output_text=final_output,
                tool_outputs=tool_outputs,
                execution_time=total_time,
                stderr=stderr_text,
                turns=result_turns,
                cost_usd=result_cost,
            )

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Claude Code execution failed: {e}")
            return ClaudeCodeCLIResult(
                success=False,
                output_text="",
                tool_outputs=[],
                execution_time=execution_time,
                stderr=str(e),
            )
