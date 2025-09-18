#!/usr/bin/env python3
"""
Minimal Codex CLI Provider

Simple wrapper for executing Codex CLI commands with MCP server integration.
Maintains minimal interface compatible with the existing agent architecture.
"""

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Optional, List, Any

from utils.logger import logger


@dataclass
class CodexCLIResult:
    """Result from a Codex CLI execution."""
    success: bool
    output_text: str
    tool_outputs: List[str]
    execution_time: float
    stderr: Optional[str] = None


class CodexCLIProvider:
    """
    Minimal provider for Codex CLI integration with MCP server support.
    """

    def __init__(self):
        """Initialize the Codex CLI provider."""
        self.codex_binary = "codex"

    def validate(self) -> bool:
        """Validate that Codex CLI is available and accessible."""
        try:
            result = subprocess.run(
                [self.codex_binary, "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                logger.info(f"Codex CLI validated successfully: {result.stdout.strip()}")
                return True
            else:
                logger.error(f"Codex CLI validation failed: {result.stderr}")
                return False
        except FileNotFoundError:
            logger.error("Codex CLI not found in PATH")
            return False
        except subprocess.TimeoutExpired:
            logger.error("Codex CLI validation timed out")
            return False
        except Exception as e:
            logger.error(f"Unexpected error validating Codex CLI: {e}")
            return False

    def call(
        self,
        input_text: str,
        mcp_config: dict,
        timeout_ms: int = 600_000,
        max_output_tokens: int = 8192
    ) -> CodexCLIResult:
        """
        Execute Codex CLI with the given input and MCP configuration.

        Args:
            input_text: The prompt/input for Codex
            mcp_config: MCP server configuration
            timeout_ms: Timeout in milliseconds
            max_output_tokens: Maximum output tokens

        Returns:
            CodexCLIResult with execution results
        """
        start_time = time.time()

        try:
            # Build Codex CLI command
            cmd = [self.codex_binary]

            # Add MCP server configuration
            if mcp_config and mcp_config.get("server_url"):
                cmd.extend(["--mcp-server", mcp_config["server_url"]])

            # Add timeout
            timeout_seconds = timeout_ms / 1000
            cmd.extend(["--timeout", str(int(timeout_seconds))])

            # Add max tokens
            cmd.extend(["--max-tokens", str(max_output_tokens)])

            # Execute Codex CLI
            logger.info(f"Executing Codex CLI: {' '.join(cmd[:3])}... (with input)")

            result = subprocess.run(
                cmd,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout_seconds + 10  # Add buffer to subprocess timeout
            )

            execution_time = time.time() - start_time

            if result.returncode == 0:
                # Parse tool outputs if available (simple parsing)
                tool_outputs = []
                if "Tool:" in result.stdout or "MCP:" in result.stdout:
                    # Extract tool interactions from output
                    lines = result.stdout.split('\n')
                    for line in lines:
                        if line.strip().startswith(('Tool:', 'MCP:')):
                            tool_outputs.append(line.strip())

                return CodexCLIResult(
                    success=True,
                    output_text=result.stdout,
                    tool_outputs=tool_outputs,
                    execution_time=execution_time,
                    stderr=result.stderr if result.stderr else None
                )
            else:
                logger.error(f"Codex CLI failed with exit code {result.returncode}")
                return CodexCLIResult(
                    success=False,
                    output_text="",
                    tool_outputs=[],
                    execution_time=execution_time,
                    stderr=result.stderr
                )

        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            logger.error(f"Codex CLI execution timed out after {execution_time:.1f}s")
            return CodexCLIResult(
                success=False,
                output_text="",
                tool_outputs=[],
                execution_time=execution_time,
                stderr="Execution timed out"
            )
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Codex CLI execution failed: {e}")
            return CodexCLIResult(
                success=False,
                output_text="",
                tool_outputs=[],
                execution_time=execution_time,
                stderr=str(e)
            )