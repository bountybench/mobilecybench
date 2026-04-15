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

            # Richer metrics: per-turn wall-clock durations, per-turn usage,
            # request/tool breakdowns, and failure counts.
            turn_start_time: Optional[float] = None
            turn_durations: List[float] = []
            per_turn_usage: List[Dict[str, Any]] = []
            failed_turns = 0
            tool_call_breakdown: Dict[str, int] = {}
            shell_exit_codes: List[int] = []
            thread_id: Optional[str] = None
            configured_model: Optional[str] = None
            if codex_config:
                maybe_model = codex_config.get("model")
                if isinstance(maybe_model, str):
                    configured_model = maybe_model
            if configured_model is None:
                maybe_default_model = config.get("model")
                if isinstance(maybe_default_model, str):
                    configured_model = maybe_default_model

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
                nonlocal turn_count, turn_start_time, thread_id, failed_turns

                event_type = data.get("type", "")
                item = data.get("item") or data.get("output_item") or {}
                item_type = item.get("type", "")

                # --- item lifecycle events ---
                if event_type == "item.completed":
                    if item_type == "command_execution":
                        cmd_str = item.get("command", "")
                        item_id = item.get("id", "")
                        exit_code = item.get("exit_code")
                        if isinstance(exit_code, int):
                            shell_exit_codes.append(exit_code)
                        tool_call_breakdown["shell"] = (
                            tool_call_breakdown.get("shell", 0) + 1
                        )
                        logger.info(f"[Codex Tool] shell: {cmd_str}")
                        agent_logger.info("tool_use name=shell command=%s", cmd_str)
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
                                "content": output if output else "",
                                "truncated": False,
                            }
                        )
                    elif item_type == "agent_message":
                        # Assistant text response
                        text = item.get("text", "")
                        if text:
                            assistant_messages.append(text)
                            current_turn_text.append(text)
                            logger.info(f"[Codex Message] {text}")
                    elif item_type == "function_call":
                        name = item.get("name", "unknown")
                        item_id = item.get("id", "")
                        tool_call_breakdown[name] = tool_call_breakdown.get(name, 0) + 1
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
                                "content": output if output else "",
                                "truncated": False,
                            }
                        )

                # --- turn lifecycle ---
                elif event_type == "turn.started":
                    turn_start_time = time.time()

                elif event_type == "turn.completed":
                    turn_count += 1
                    if turn_start_time is not None:
                        turn_durations.append(time.time() - turn_start_time)
                        turn_start_time = None
                    usage = data.get("usage", {})
                    if usage:
                        per_turn_usage.append(dict(usage))
                        token_usage["input_tokens"] += usage.get("input_tokens", 0)
                        token_usage["output_tokens"] += usage.get("output_tokens", 0)
                        cached = usage.get("cached_input_tokens", 0)
                        if cached:
                            token_usage["cached_input_tokens"] = (
                                token_usage.get("cached_input_tokens", 0) + cached
                            )
                        # Reasoning tokens: codex has not shipped this field
                        # as of the current CLI (tracked upstream in
                        # openai/codex#5276), but accept whichever naming it
                        # lands on so we capture them automatically.
                        reasoning = (
                            usage.get("reasoning_output_tokens")
                            or usage.get("reasoning_tokens")
                            or 0
                        )
                        if reasoning:
                            token_usage["reasoning_output_tokens"] = token_usage.get(
                                "reasoning_output_tokens", 0
                            ) + int(reasoning)
                    duration_msg = ""
                    if turn_durations:
                        duration_msg = f" ({turn_durations[-1]:.1f}s)"
                    logger.info(f"[Codex] Turn {turn_count} completed{duration_msg}")
                    _flush_turn()

                elif event_type == "turn.failed":
                    failed_turns += 1
                    # Reset timer so the next turn's duration is measured
                    # from its own turn.started event.
                    turn_start_time = None
                    err = data.get("error") or data.get("message") or {}
                    logger.error(f"[Codex] Turn failed: {err}")

                elif event_type == "thread.started":
                    tid = data.get("thread_id")
                    if isinstance(tid, str):
                        thread_id = tid

                elif event_type == "error":
                    msg = data.get("message", "")
                    logger.error(f"[Codex Error] {msg}")

                # --- informational events ---
                elif event_type in ("item.started",):
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
            if turn_durations:
                mean_dur = sum(turn_durations) / len(turn_durations)
                logger.info(
                    f"[Codex] {len(turn_durations)} model requests, "
                    f"total={sum(turn_durations):.1f}s, "
                    f"mean={mean_dur:.1f}s, max={max(turn_durations):.1f}s"
                )

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
                thread_id=thread_id,
                turn_durations=turn_durations,
                per_turn_usage=per_turn_usage,
                failed_turns=failed_turns,
                tool_call_breakdown=tool_call_breakdown,
                shell_exit_codes=shell_exit_codes,
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
