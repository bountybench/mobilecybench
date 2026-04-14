#!/usr/bin/env python3

import json
import time
from typing import Any, Dict, List, Optional

import docker
from pydantic import BaseModel

from utils.docker_utils import run_command_in_container
from utils.logger import agent_logger, logger
from utils.run_artifacts import utc_now_iso


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

            # State for callbacks
            tool_outputs = []
            assistant_messages = []
            conversation_events: List[dict] = []
            result_turns = 0
            result_cost = None
            cli_session_id: Optional[str] = None
            cli_result_payload: Optional[Dict[str, Any]] = None

            # Buffer for incomplete lines across chunks.  Docker streaming
            # can split a JSON line across multiple callbacks.
            line_buffer = ""

            # Accumulate per-turn data for conversation_events
            current_turn = 1  # schema requires turn_number >= 1
            current_turn_text = []
            current_turn_tool_calls = []
            current_turn_observations = []
            current_turn_reasoning = []

            def _flush_turn():
                """Flush accumulated turn data into a conversation event."""
                nonlocal current_turn
                if not current_turn_text and not current_turn_tool_calls:
                    return
                conversation_events.append(
                    {
                        "turn": current_turn,
                        "timestamp": utc_now_iso(),
                        "assistant_text": "\n".join(current_turn_text),
                        "reasoning_summary": "\n".join(current_turn_reasoning),
                        "tool_calls": list(current_turn_tool_calls),
                        "observations": list(current_turn_observations),
                    }
                )
                current_turn_text.clear()
                current_turn_tool_calls.clear()
                current_turn_observations.clear()
                current_turn_reasoning.clear()
                current_turn += 1

            def parse_output_chunk(text: str):
                """Parse JSONL chunks from stdout."""
                nonlocal result_turns, result_cost, current_turn, line_buffer
                nonlocal cli_session_id, cli_result_payload

                # Prepend any leftover partial line from previous chunk
                text = line_buffer + text
                line_buffer = ""

                lines = text.split("\n")
                # If the chunk doesn't end with newline, the last element
                # is an incomplete line — save it for the next chunk.
                if not text.endswith("\n"):
                    line_buffer = lines.pop()

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        event_type = data.get("type")

                        if event_type == "system":
                            subtype = data.get("subtype")
                            if subtype == "init":
                                cli_session_id = data.get("session_id", "unknown")
                                logger.info(
                                    f"[ClaudeCode] Session started: {cli_session_id}"
                                )

                        elif event_type == "assistant":
                            message = data.get("message", {})
                            for content in message.get("content", []):
                                content_type = content.get("type")
                                if content_type == "text":
                                    text_content = content.get("text", "")
                                    if text_content:
                                        assistant_messages.append(text_content)
                                        current_turn_text.append(text_content)
                                        logger.info(
                                            f"[ClaudeCode Message] {text_content}"
                                        )
                                elif content_type == "thinking":
                                    thinking_text = content.get("thinking", "")
                                    if thinking_text:
                                        current_turn_reasoning.append(thinking_text)
                                elif content_type == "tool_use":
                                    tool_name = content.get("name", "unknown")
                                    tool_input = content.get("input", {})
                                    tool_id = content.get("id", "")
                                    current_turn_tool_calls.append(
                                        {
                                            "name": tool_name,
                                            "tool_call_id": tool_id,
                                            "arguments": tool_input,
                                        }
                                    )
                                    logger.info(
                                        f"[ClaudeCode Tool] {tool_name} input={json.dumps(tool_input)}"
                                    )
                                    agent_logger.info(
                                        "tool_use name=%s input=%s",
                                        tool_name,
                                        json.dumps(tool_input),
                                    )

                        elif event_type == "user":
                            message = data.get("message", {})
                            for content in message.get("content", []):
                                if content.get("type") == "tool_result":
                                    tool_outputs.append(json.dumps(content))
                                    raw_content = content.get("content", "")
                                    # content can be a string or a list of blocks
                                    if isinstance(raw_content, list):
                                        tool_content = "\n".join(
                                            b.get("text", str(b)) for b in raw_content
                                        )
                                    else:
                                        tool_content = raw_content
                                    tool_id = content.get("tool_use_id", "")
                                    current_turn_observations.append(
                                        {
                                            "tool_use_id": tool_id,
                                            "content": tool_content,
                                        }
                                    )
                                    agent_logger.info(
                                        "tool_result content=%s", tool_content
                                    )
                            # A user event (tool results) marks the end of a turn
                            _flush_turn()

                        elif event_type == "result":
                            result_turns = data.get("num_turns", 0)
                            result_cost = data.get("total_cost_usd")
                            subtype = data.get("subtype")
                            # Capture the full result event for token/cost parsing
                            cli_result_payload = data
                            # Flush any remaining turn data
                            _flush_turn()
                            if subtype == "success":
                                cost_str = (
                                    f"${result_cost:.4f}" if result_cost else "N/A"
                                )
                                logger.info(
                                    f"[ClaudeCode] Completed: {result_turns} turns, cost={cost_str}"
                                )
                            elif subtype == "error":
                                logger.error(f"[ClaudeCode] Error: {data.get('error')}")

                    except json.JSONDecodeError:
                        # Raw output (not JSON)
                        if line.strip():
                            logger.info(f"[ClaudeCode Raw] {line.strip()}")

            def handle_stderr(text: str):
                """Log stderr lines in real time."""
                for line in text.splitlines():
                    line = line.strip()
                    if line:
                        logger.warning(f"[ClaudeCode stderr] {line}")

            # Execute using shared helper
            _, stderr_text, exit_code = run_command_in_container(
                self.container_name,
                cmd,
                timeout_sec,
                stdout_callback=parse_output_chunk,
                stderr_callback=handle_stderr,
            )

            final_output = "\n".join(assistant_messages)

            total_time = time.time() - start_time
            logger.info(f"Completed Claude Code execution in {total_time:.1f}s")
            logger.info(f"Exit code: {exit_code}")
            logger.info(f"Output length: {len(final_output)} chars")
            if stderr_text:
                logger.warning(f"Stderr: {stderr_text}")

            # Flush any turn data not yet flushed (e.g. final assistant
            # message with no subsequent user event)
            _flush_turn()

            return ClaudeCodeCLIResult(
                success=(exit_code == 0),
                output_text=final_output,
                tool_outputs=tool_outputs,
                execution_time=total_time,
                stderr=stderr_text,
                exit_code=exit_code,
                turns=result_turns,
                cost_usd=result_cost,
                conversation_events=conversation_events,
                session_id=cli_session_id,
                result_payload=cli_result_payload,
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
