#!/usr/bin/env python3

import json
import time
from typing import Any, Dict, List, Optional

import docker
from pydantic import BaseModel

from utils.docker_utils import run_command_in_container
from utils.logger import agent_logger, logger


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
                "model": "gpt-5.2",
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

            # State for callbacks
            tool_outputs = []
            assistant_messages = []
            turn_count = 0

            # Conversation event tracking (per-turn accumulation)
            current_turn_tool_calls = []
            current_turn_observations = []
            current_turn_text = []
            conversation_events = []

            # Buffer for incomplete lines across chunks.  Docker streaming
            # delivers raw byte chunks that can split a JSONL line.
            line_buffer = ""

            # Token usage accumulator
            token_usage = {"input_tokens": 0, "output_tokens": 0}

            def _flush_turn():
                """Flush the current turn's accumulated events."""
                if not current_turn_tool_calls and not current_turn_text:
                    return
                conversation_events.append(
                    {
                        "turn": turn_count,
                        "assistant_text": "\n".join(current_turn_text),
                        "tool_calls": list(current_turn_tool_calls),
                        "observations": list(current_turn_observations),
                    }
                )
                current_turn_tool_calls.clear()
                current_turn_observations.clear()
                current_turn_text.clear()

            def _handle_event(data: dict):
                """Handle a single parsed JSONL event from codex --json."""
                nonlocal turn_count

                event_type = data.get("type", "")
                item = data.get("item") or data.get("output_item") or {}
                item_type = item.get("type", "")

                # --- item lifecycle events ---
                if event_type == "item.completed":
                    if item_type == "command_execution":
                        cmd_str = item.get("command", "")
                        item_id = item.get("id", "")
                        logger.info(f"[Codex Tool] shell: {cmd_str[:200]}")
                        agent_logger.info(
                            "tool_use name=shell command=%s", cmd_str[:200]
                        )
                        output = item.get("aggregated_output") or item.get("output", "")
                        if output:
                            tool_outputs.append(output)
                            agent_logger.info(
                                "tool_result has_content=%s", bool(output)
                            )
                        # Track for conversation events
                        current_turn_tool_calls.append(
                            {
                                "tool_call_id": item_id,
                                "name": "shell",
                                "arguments": {"command": cmd_str},
                            }
                        )
                        current_turn_observations.append(
                            {
                                "tool_call_id": item_id,
                                "type": "tool_result",
                                "content": output[:10000] if output else "",
                                "truncated": len(output) > 10000 if output else False,
                            }
                        )
                    elif item_type == "agent_message":
                        # Assistant text response
                        text = item.get("text", "")
                        if text:
                            assistant_messages.append(text)
                            current_turn_text.append(text)
                            preview = (text[:200] + "...") if len(text) > 200 else text
                            logger.info(f"[Codex Message] {preview}")
                    elif item_type == "function_call":
                        name = item.get("name", "unknown")
                        item_id = item.get("id", "")
                        logger.info(f"[Codex Tool] {name}")
                        agent_logger.info("tool_use name=%s", name)
                        current_turn_tool_calls.append(
                            {
                                "tool_call_id": item_id,
                                "name": name,
                                "arguments": item.get("arguments", {}),
                            }
                        )
                    elif item_type == "function_call_output":
                        output = item.get("output", "")
                        item_id = item.get("call_id", item.get("id", ""))
                        if output:
                            tool_outputs.append(output)
                        current_turn_observations.append(
                            {
                                "tool_call_id": item_id,
                                "type": "tool_result",
                                "content": output[:10000] if output else "",
                                "truncated": len(output) > 10000 if output else False,
                            }
                        )

                # --- turn lifecycle ---
                elif event_type == "turn.completed":
                    turn_count += 1
                    usage = data.get("usage", {})
                    if usage:
                        token_usage["input_tokens"] += usage.get("input_tokens", 0)
                        token_usage["output_tokens"] += usage.get("output_tokens", 0)
                        cached = usage.get("cached_input_tokens", 0)
                        if cached:
                            token_usage["cached_input_tokens"] = (
                                token_usage.get("cached_input_tokens", 0) + cached
                            )
                    logger.info(f"[Codex] Turn {turn_count} completed")
                    _flush_turn()

                elif event_type == "error":
                    msg = data.get("message", "")
                    logger.error(f"[Codex Error] {msg}")

                # --- informational events ---
                elif event_type in ("thread.started", "turn.started", "item.started"):
                    pass

                # --- catch-all ---
                else:
                    logger.debug(f"[Codex Event] {event_type}")

            def parse_output_chunk(text: str):
                """Parse JSONL chunks from stdout with line buffering."""
                nonlocal line_buffer

                text = line_buffer + text
                line_buffer = ""

                lines = text.split("\n")
                # Last element is either "" (line ended with \n) or a partial
                # line — save it for the next chunk.
                if not text.endswith("\n"):
                    line_buffer = lines.pop()
                else:
                    lines.pop()  # remove trailing empty string

                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        _handle_event(data)
                    except json.JSONDecodeError:
                        if line:
                            logger.info(f"[Codex Raw] {line}")

            # Execute using helper
            _, stderr_text, exit_code = run_command_in_container(
                self.container_name,
                cmd,
                timeout_sec,
                stdout_callback=parse_output_chunk,
            )

            # Flush any remaining buffered partial line
            if line_buffer.strip():
                try:
                    data = json.loads(line_buffer.strip())
                    _handle_event(data)
                except json.JSONDecodeError:
                    logger.info(f"[Codex Raw] {line_buffer.strip()}")

            # Flush any remaining turn data
            _flush_turn()

            final_output = "\n".join(assistant_messages)

            total_time = time.time() - start_time
            logger.info(f"🏁 Completed execution in {total_time:.1f}s")
            logger.info(f"Output length: {len(final_output)} chars")

            return CodexCLIResult(
                success=(exit_code == 0),
                output_text=final_output,
                tool_outputs=tool_outputs,
                execution_time=total_time,
                stderr=stderr_text,
                exit_code=exit_code,
                turns=turn_count,
                conversation_events=conversation_events,
                token_usage=token_usage,
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
