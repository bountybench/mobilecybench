#!/usr/bin/env python3

import json
import logging
import time
from dataclasses import dataclass
from typing import List, Optional

import docker

from utils.docker_utils import run_command_in_container
from utils.logger import logger, logger_manager

# Create dedicated logger for tool interactions
tool_logger = logging.getLogger("MobileCyBench.ToolInteractions")
if not tool_logger.handlers:
    logs_dir = logger_manager.get_logs_dir()
    file_handler = logging.FileHandler(str(logs_dir / "mobile_security_analysis.log"))
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    tool_logger.addHandler(file_handler)
    tool_logger.setLevel(logging.INFO)


@dataclass
class CodexCLIResult:
    """Result from a Codex CLI execution."""

    success: bool
    output_text: str
    tool_outputs: List[str]
    execution_time: float
    stderr: Optional[str] = None
    turns: int = 0


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
    ) -> CodexCLIResult:
        """
        Execute Codex CLI in single-iteration mode (no session resumption).
        """
        start_time = time.time()
        timeout_sec = timeout_ms / 1000

        try:
            # Default to /app/codebase inside container if not specified
            app_codebase_dir = "/app/codebase"

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
                "model_reasoning_effort": "xhigh",
                "model": "gpt-5.1-codex-max",
                "model_reasoning_summary": "detailed",
                "model_verbosity": "high",
            }
            if codex_config:
                config.update(codex_config)

            # Construct command
            # We inject PYTHONUNBUFFERED=1 to ensure Python flushing if codex is Python-based
            # stdbuf is used to force line buffering

            # Base command: stdbuf -oL -eL codex
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

            def parse_output_chunk(text: str):
                """Parse JSONL chunks from stdout."""
                for line in text.strip().split("\n"):
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        event_type = data.get("type")

                        if event_type == "log":
                            content = data.get("content", "").strip()
                            if content:
                                logger.info(f"[Codex Log] {content}")
                        elif event_type == "tool_use":
                            tool = data.get("name", "unknown")
                            logger.info(f"[Codex Tool] Using tool: {tool}")
                        elif event_type == "assistant_message":
                            content = data.get("content", "")
                            if content:
                                assistant_messages.append(content)
                                preview = (
                                    (content[:200] + "...")
                                    if len(content) > 200
                                    else content
                                )
                                logger.info(f"[Codex Message] {preview}")
                        elif event_type == "tool_result":
                            tool_outputs.append(json.dumps(data.get("content", {})))

                    except json.JSONDecodeError:
                        # Raw output (not JSON)
                        if line.strip():
                            logger.info(f"[Codex Raw] {line.strip()}")

            # Execute using helper
            # Note: run_command_in_container returns (stdout, stderr, exit_code)
            _, stderr_text, exit_code = run_command_in_container(
                self.container_name,
                cmd,
                timeout_sec,
                stdout_callback=parse_output_chunk,
            )

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
