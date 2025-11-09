#!/usr/bin/env python3
"""
Codex CLI Provider with Experiment-Scoped Session Management

Uses explicit session files per experiment to ensure parallel safety
and proper session resumption across multi-turn executions.
"""

import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from utils.logger import logger

# Create dedicated logger for tool interactions
tool_logger = logging.getLogger("MobileCyBench.ToolInteractions")
if not tool_logger.handlers:
    file_handler = logging.FileHandler("/tmp/mobile_security_analysis.log")
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
    experiment_id: Optional[str] = None
    session_file: Optional[str] = None


class CodexCLIProvider:
    """
    Codex CLI provider with experiment-scoped session management.

    Each experiment gets a unique session file to ensure:
    - Parallel execution safety (no race conditions)
    - Proper session resumption across turns
    - Clean isolation between experiments
    """

    def __init__(self, experiment_id: str):
        """
        Initialize the Codex CLI provider for a specific experiment.

        Args:
            experiment_id: Unique identifier for this experiment
                          (e.g., "app1_task5_run3" or UUID)
        """
        self.codex_binary = "codex"
        self.experiment_id = experiment_id

        # Create dedicated sessions directory for experiments
        self.sessions_dir = Path.home() / ".codex" / "sessions" / "experiments"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        # Each experiment gets its own session file
        self.session_file = self.sessions_dir / f"{experiment_id}.jsonl"

        logger.info(f"CodexCLIProvider initialized for experiment: {experiment_id}")
        logger.info(f"Session file: {self.session_file}")

    def validate(self) -> bool:
        """Validate that Codex CLI is available and accessible."""
        try:
            result = subprocess.run(
                [self.codex_binary, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                logger.info(f"Codex CLI binary found: {result.stdout.strip()}")

                # Check for OPENAI_API_KEY
                if not os.getenv("OPENAI_API_KEY"):
                    logger.warning("OPENAI_API_KEY environment variable not set")
                    logger.warning("Codex CLI requires OpenAI API key to function")
                    return False

                logger.info("Codex CLI validated with OPENAI_API_KEY")
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

    def execute(
        self,
        prompt: str,
        mcp_config: dict,
        timeout_ms: int = 600_000,
        max_iterations: int = 30,
    ) -> CodexCLIResult:
        """
        Execute Codex CLI in multi-turn mode with experiment-scoped sessions.

        Starts with initial exec, then loops with resume until:
        - Agent outputs "FinalSubmissionCommand"
        - Max iterations reached
        - Timeout expires

        Args:
            prompt: The initial instructions for the agent
            mcp_config: MCP server configuration
            timeout_ms: Timeout in milliseconds for entire execution
            max_iterations: Maximum number of turns to execute

        Returns:
            CodexCLIResult with execution results
        """
        start_time = time.time()

        try:
            # Get configuration
            app_codebase_dir = (
                mcp_config.get("app_codebase_dir", "/tmp") if mcp_config else "/tmp"
            )
            server_url = mcp_config.get("server_url") if mcp_config else None

            # Validate MCP server URL
            if server_url:
                allowed_hosts = [
                    "localhost",
                    "127.0.0.1",
                    "mcp-server",
                    "ngrok-free.dev",
                ]
                if not any(host in server_url for host in allowed_hosts):
                    logger.warning(f"Rejecting non-secure MCP server: {server_url}")
                    return CodexCLIResult(
                        success=False,
                        output_text="",
                        tool_outputs=[],
                        execution_time=time.time() - start_time,
                        stderr="Security policy: Only secure MCP servers allowed",
                        experiment_id=self.experiment_id,
                        session_file=str(self.session_file),
                    )
                logger.info(f"Using MCP server: {server_url}")

            # Check if this is a new session or resuming existing one
            is_new_session = not self.session_file.exists()

            if is_new_session:
                logger.info(
                    f"🚀 Starting NEW session for experiment: {self.experiment_id}"
                )
            else:
                logger.info(
                    f"🔄 RESUMING existing session for experiment: {self.experiment_id}"
                )

            logger.info(f"Working directory: {app_codebase_dir}")
            logger.info(f"Max iterations: {max_iterations}, Timeout: {timeout_ms}ms")

            # Initial execution
            result = self._run_codex_turn(
                prompt,
                app_codebase_dir,
                timeout_ms,
                is_initial=is_new_session,
            )

            if not result.success:
                return result

            turn_count = 1
            final_output = result.output_text
            all_tool_outputs = result.tool_outputs

            logger.info(f"✅ Turn 1 completed in {result.execution_time:.1f}s")
            logger.info(f"Output: {final_output}")

            # Continue with resume until done
            while turn_count < max_iterations:
                # Check for stop condition
                if "FinalSubmissionCommand" in final_output:
                    logger.info(
                        f"🛑 Found FinalSubmissionCommand after {turn_count} turns"
                    )
                    break

                # Check timeout
                elapsed_ms = (time.time() - start_time) * 1000
                if elapsed_ms >= timeout_ms:
                    logger.warning(
                        f"⏱ Timeout reached ({elapsed_ms:.0f}ms), stopping execution"
                    )
                    break

                # Resume session
                remaining_timeout = timeout_ms - int(elapsed_ms)
                logger.info(
                    f"🔁 Resuming session (turn {turn_count + 1}/{max_iterations})"
                )

                result = self._run_codex_turn(
                    prompt,  # Pass original prompt for context (not used in resume)
                    app_codebase_dir,
                    remaining_timeout,
                    is_initial=False,
                )

                if not result.success:
                    logger.warning(
                        f"⚠️ Resume failed after {turn_count} turns: {result.stderr}"
                    )
                    break

                turn_count += 1
                final_output = result.output_text
                all_tool_outputs.extend(result.tool_outputs)

                logger.info(f"✅ Turn {turn_count} completed in {result.execution_time:.1f}s")
                logger.info(f"Output: {final_output}")

                # If output is empty, session might be done
                if not final_output.strip():
                    logger.info("Empty output received, assuming session complete")
                    break

            total_time = time.time() - start_time
            logger.info(
                f"🏁 Experiment {self.experiment_id} completed {turn_count} turns in {total_time:.1f}s"
            )

            # Log final output
            tool_logger.info(
                f"Multi-turn execution completed for {self.experiment_id}. Turns: {turn_count}"
            )
            tool_logger.info(f"Final output length: {len(final_output)} chars")
            tool_logger.info(f"Full output:\n{final_output}")

            return CodexCLIResult(
                success=True,
                output_text=final_output,
                tool_outputs=all_tool_outputs,
                execution_time=total_time,
                experiment_id=self.experiment_id,
                session_file=str(self.session_file),
            )

        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            logger.error(f"Codex execution timed out after {execution_time:.1f}s")
            return CodexCLIResult(
                success=False,
                output_text="",
                tool_outputs=[],
                execution_time=execution_time,
                stderr=f"Execution timed out after {timeout_ms}ms",
                experiment_id=self.experiment_id,
                session_file=str(self.session_file),
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
                experiment_id=self.experiment_id,
                session_file=str(self.session_file),
            )

    def _run_codex_turn(
        self,
        prompt: str,
        app_codebase_dir: str,
        timeout_ms: int,
        is_initial: bool,
    ) -> CodexCLIResult:
        """
        Run a single Codex turn (either initial exec or resume).

        Args:
            prompt: Initial prompt for exec
            app_codebase_dir: Working directory
            timeout_ms: Timeout in milliseconds
            is_initial: True for new session, False for resume

        Returns:
            CodexCLIResult with turn results
        """
        turn_start = time.time()

        # Create temp files for output
        output_file = tempfile.NamedTemporaryFile(
            mode="w+", suffix=".txt", delete=False
        )
        jsonl_file = tempfile.NamedTemporaryFile(
            mode="w+", suffix=".jsonl", delete=False
        )

        try:
            if is_initial:
                # Build codex exec command for NEW session
                cmd = [
                    self.codex_binary,
                    "exec",
                    "--dangerously-bypass-approvals-and-sandbox",
                    "--skip-git-repo-check",
                    "--json",
                    "-o",
                    output_file.name,
                    "-C",
                    app_codebase_dir,
                    prompt,
                ]
                logger.info(f"Executing NEW session: {' '.join(cmd)}")
            else:
                # Build codex resume command for EXISTING session
                # Use experimental_resume with our specific session file
                cmd = [
                    self.codex_binary,
                    "-c",
                    f"experimental_resume={self.session_file}",
                    "exec",
                    "--dangerously-bypass-approvals-and-sandbox",
                    "--skip-git-repo-check",
                    "--json",
                    "-o",
                    output_file.name,
                    "-C",
                    app_codebase_dir,
                    prompt,
                ]
                logger.info(
                    f"Resuming EXISTING session from: {self.session_file.name}"
                )

            # Execute command
            env = os.environ.copy()
            with open(jsonl_file.name, "w") as jsonl_out:
                result = subprocess.run(
                    cmd,
                    stdin=subprocess.DEVNULL,  # Close stdin to prevent waiting
                    stdout=jsonl_out,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=timeout_ms / 1000,
                    env=env,
                )

            execution_time = time.time() - turn_start

            # Read outputs
            output_file.seek(0)
            final_output = output_file.read()

            jsonl_file.seek(0)
            jsonl_content = jsonl_file.read()

            # Parse JSONL events to extract tool outputs
            tool_outputs = []
            for line in jsonl_content.strip().split("\n"):
                if line:
                    try:
                        event = json.loads(line)
                        if event.get("type") == "tool_result":
                            tool_outputs.append(json.dumps(event.get("content", {})))
                    except json.JSONDecodeError:
                        continue

            if result.returncode == 0:

                return CodexCLIResult(
                    success=True,
                    output_text=final_output,
                    tool_outputs=tool_outputs,
                    execution_time=execution_time,
                    experiment_id=self.experiment_id,
                    session_file=str(self.session_file),
                )
            else:
                logger.error(f"Codex turn failed with code {result.returncode}")
                logger.error(f"stderr: {result.stderr}")

                # Provide helpful error messages
                if "No such device or address" in str(result.stderr):
                    auth_error = "Codex CLI authentication required. Please run 'codex login'"
                    logger.error(auth_error)
                    return CodexCLIResult(
                        success=False,
                        output_text=final_output,
                        tool_outputs=tool_outputs,
                        execution_time=execution_time,
                        stderr=auth_error,
                        experiment_id=self.experiment_id,
                        session_file=str(self.session_file),
                    )
                elif "OPENAI_API_KEY" in str(result.stderr):
                    api_key_error = "OPENAI_API_KEY environment variable required"
                    logger.error(api_key_error)
                    return CodexCLIResult(
                        success=False,
                        output_text=final_output,
                        tool_outputs=tool_outputs,
                        execution_time=execution_time,
                        stderr=api_key_error,
                        experiment_id=self.experiment_id,
                        session_file=str(self.session_file),
                    )

                return CodexCLIResult(
                    success=False,
                    output_text=final_output,
                    tool_outputs=tool_outputs,
                    execution_time=execution_time,
                    stderr=result.stderr,
                    experiment_id=self.experiment_id,
                    session_file=str(self.session_file),
                )

        except subprocess.TimeoutExpired:
            execution_time = time.time() - turn_start
            logger.error(f"Codex turn timed out after {execution_time:.1f}s")
            return CodexCLIResult(
                success=False,
                output_text="",
                tool_outputs=[],
                execution_time=execution_time,
                stderr="Turn timed out",
                experiment_id=self.experiment_id,
                session_file=str(self.session_file),
            )
        except Exception as e:
            execution_time = time.time() - turn_start
            logger.error(f"Codex turn failed: {e}")
            return CodexCLIResult(
                success=False,
                output_text="",
                tool_outputs=[],
                execution_time=execution_time,
                stderr=str(e),
                experiment_id=self.experiment_id,
                session_file=str(self.session_file),
            )
        finally:
            # Cleanup temp files
            output_file.close()
            jsonl_file.close()
            try:
                os.unlink(output_file.name)
                os.unlink(jsonl_file.name)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp files: {e}")

    def cleanup(self):
        """
        Clean up experiment session file.

        Call this after experiment completes to free up disk space.
        """
        try:
            if self.session_file.exists():
                self.session_file.unlink()
                logger.info(
                    f"Cleaned up session file for experiment: {self.experiment_id}"
                )
            else:
                logger.info(f"No session file to clean up for: {self.experiment_id}")
        except Exception as e:
            logger.warning(f"Error cleaning up session file: {e}")

    def get_session_info(self) -> dict:
        """
        Get information about the current session.

        Returns:
            dict: Session metadata including file path, size, and modification time
        """
        info = {
            "experiment_id": self.experiment_id,
            "session_file": str(self.session_file),
            "exists": self.session_file.exists(),
        }

        if self.session_file.exists():
            stat = self.session_file.stat()
            info.update(
                {
                    "size_bytes": stat.st_size,
                    "modified_time": stat.st_mtime,
                    "modified_time_str": time.ctime(stat.st_mtime),
                }
            )

        return info