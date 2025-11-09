#!/usr/bin/env python3
"""
Minimal Codex CLI Provider

Simple wrapper for executing Codex CLI commands with MCP server integration.
Maintains minimal interface compatible with the existing agent architecture.
"""

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from utils.logger import logger

# Create dedicated logger for tool interactions
tool_logger = logging.getLogger("MobileCyBench.ToolInteractions")
if not tool_logger.handlers:
    # Add file handler for tool interactions
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
    session_id: Optional[str] = None
    session_file: Optional[str] = None


class CodexCLIProvider:
    """
    Enhanced Codex CLI provider with session management and context caching.
    Leverages Codex CLI's built-in session resumption and prompt caching capabilities.
    """

    def __init__(self):
        """Initialize the Codex CLI provider with session management."""
        self.codex_binary = "codex"
        self.session_id: Optional[str] = None
        self.session_file: Optional[str] = None
        self.first_call = True
        self.sessions_dir = Path.home() / ".codex" / "sessions"

        # Ensure sessions directory exists
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        logger.info("CodexCLIProvider initialized with session management support")
        logger.info(f"Sessions directory: {self.sessions_dir}")

    def validate(self) -> bool:
        """Validate that Codex CLI is available and accessible."""
        try:
            # Check if Codex CLI binary exists
            result = subprocess.run(
                [self.codex_binary, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                logger.info(f"Codex CLI binary found: {result.stdout.strip()}")

                # Check for OPENAI_API_KEY (required for API-based authentication)
                import os

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

    def _discover_recent_session(self) -> Optional[Dict[str, str]]:
        """Discover session for this run with limited global fallback for new sessions."""
        try:
            # First priority: Check for run-specific session
            run_session = self._load_run_session()
            if run_session:
                logger.info(f"Using run-specific session: {run_session['session_id']}")
                return run_session

            # Second priority: For first call only, allow limited global discovery
            # of very recent sessions (last 2 minutes) to find newly created sessions
            if self.first_call:
                session_files = list(self.sessions_dir.glob("*/*/*/*rollout*.jsonl"))
                if session_files:
                    # Filter to very recent sessions (last 2 minutes only)
                    current_time = time.time()
                    very_recent_sessions = [
                        f
                        for f in session_files
                        if (current_time - f.stat().st_mtime) < 120  # 2 minutes
                    ]

                    if very_recent_sessions:
                        # Sort by modification time to get most recent
                        very_recent_sessions.sort(
                            key=lambda f: f.stat().st_mtime, reverse=True
                        )
                        most_recent = very_recent_sessions[0]

                        # Extract session ID from filename
                        session_id = most_recent.stem.replace("rollout-", "")

                        logger.info(
                            f"Found newly created session for first call: {most_recent.name}"
                        )
                        return {
                            "session_id": session_id,
                            "session_file": str(most_recent),
                            "modified": str(most_recent.stat().st_mtime),
                        }

            logger.info("No session found for this run")
            return None
        except Exception as e:
            logger.warning(f"Error discovering sessions: {e}")
            return None

    def _get_run_session_file(self) -> str:
        """Get the run-specific session file path."""
        # Use parent process PID to ensure same run uses same session file
        parent_pid = os.getppid()
        return f"/tmp/codex_run_session_{parent_pid}.txt"

    def _save_run_session(self, session_id: str, session_file: str) -> None:
        """Save session information for this specific run."""
        try:
            run_session_file = self._get_run_session_file()
            session_data = {
                "session_id": session_id,
                "session_file": session_file,
                "created_at": time.time(),
                "pid": os.getpid(),
                "parent_pid": os.getppid(),
            }
            with open(run_session_file, "w") as f:
                json.dump(session_data, f)
            logger.info(f"Saved run-specific session: {session_id}")
        except Exception as e:
            logger.warning(f"Failed to save run session: {e}")

    def _load_run_session(self) -> Optional[Dict[str, str]]:
        """Load session information for this specific run."""
        try:
            run_session_file = self._get_run_session_file()
            if not os.path.exists(run_session_file):
                return None

            with open(run_session_file, "r") as f:
                session_data = json.load(f)

            # Validate session file still exists
            session_file = session_data.get("session_file")
            if not session_file or not os.path.exists(session_file):
                logger.warning(f"Run session file no longer exists: {session_file}")
                return None

            # Check age (sessions older than 1 hour are considered stale)
            created_at = session_data.get("created_at", 0)
            if time.time() - created_at > 3600:
                logger.warning("Run session is stale (>1 hour old)")
                return None

            logger.info(f"Loaded run-specific session: {session_data['session_id']}")
            return session_data
        except Exception as e:
            logger.warning(f"Failed to load run session: {e}")
            return None

    def _should_resume_session(self) -> bool:
        """Determine if we should resume an existing session."""
        # First call: Never resume (always start fresh per run)
        if self.first_call:
            return False

        # Later calls: Only resume if we have session from current run
        return self.session_id is not None

    def _create_new_session_command(
        self, enhanced_input: str, app_codebase_dir: str
    ) -> List[str]:
        """Create command for starting a new Codex CLI session."""
        cmd = [self.codex_binary, "exec"]

        # Use secure workspace mode with minimal write access for ADB
        cmd.extend(["--sandbox", "workspace-write"])
        cmd.extend(["--skip-git-repo-check"])  # Allow running outside git repo

        # Set working directory to app codebase
        cmd.extend(["-C", app_codebase_dir])

        # Add the input as the final argument
        cmd.append(enhanced_input)

        logger.info("Creating new Codex CLI session")
        return cmd

    def _create_resume_session_command(
        self, enhanced_input: str, app_codebase_dir: str
    ) -> List[str]:
        """Create command for resuming an existing Codex CLI session."""
        # Use experimental resume to preserve conversation history with fresh MCP connections
        logger.info(
            f"Using experimental resume with validated session file: {self.session_file}"
        )
        cmd = [
            self.codex_binary,
            "-c",
            f"experimental_resume={self.session_file}",
            "exec",
            "--skip-git-repo-check",  # Required for non-git directories
            "--sandbox",
            "workspace-write",  # Consistent with new session settings
            "-C",
            app_codebase_dir,
            enhanced_input,
        ]
        return cmd

    def _update_session_info_from_output(self) -> None:
        """Extract session information from filesystem and update internal state."""
        try:
            # Check if we already have a run-specific session that should be preserved
            run_session = self._load_run_session()
            if run_session and self.session_id == run_session["session_id"]:
                logger.info(f"Preserving run-specific session: {self.session_id}")
                return

            # If we don't have a session ID yet, or it's a new session, discover and update
            session_info = self._discover_recent_session()
            if session_info:
                old_session_id = self.session_id
                self.session_id = session_info["session_id"]
                self.session_file = session_info["session_file"]

                # If this is a new session (not resuming), save it as run-specific
                if self.first_call and old_session_id != self.session_id:
                    self._save_run_session(self.session_id, self.session_file)
                    logger.info(f"Saved new session as run-specific: {self.session_id}")

                logger.info(
                    f"Updated session info - ID: {self.session_id}, File: {self.session_file}"
                )

        except Exception as e:
            logger.warning(f"Error updating session info: {e}")

    def _handle_session_failure(
        self, error: Exception, app_codebase_dir: str, enhanced_input: str
    ) -> Optional[subprocess.CompletedProcess]:
        """
        Handle session failures with automatic recovery mechanisms.

        Args:
            error: The exception that occurred
            app_codebase_dir: App codebase directory
            enhanced_input: The enhanced input prompt

        Returns:
            subprocess.CompletedProcess if recovery succeeds, None otherwise
        """
        logger.warning(f"Session failure occurred: {error}")
        logger.info("Attempting session recovery...")

        # Recovery Strategy 1: Try experimental resume if session file exists
        if self.session_file and os.path.exists(self.session_file):
            try:
                logger.info(
                    f"Attempting experimental resume with session file: {self.session_file}"
                )
                cmd = [
                    self.codex_binary,
                    "-c",
                    f"experimental_resume={self.session_file}",
                    "exec",
                    "--skip-git-repo-check",  # Required for non-git directories
                    "--sandbox",
                    "workspace-write",  # Consistent with new session settings
                    "-C",
                    app_codebase_dir,
                    enhanced_input,
                ]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,  # Shorter timeout for recovery
                )

                if result.returncode == 0:
                    logger.info("Experimental resume recovery succeeded")
                    return result
                else:
                    logger.warning(f"Experimental resume failed: {result.stderr}")

            except Exception as e:
                logger.warning(f"Experimental resume recovery failed: {e}")

        # Recovery Strategy 2: Fall back to fresh session
        try:
            logger.info("Falling back to fresh session")
            # Reset session state
            self.session_id = None
            self.session_file = None
            self.first_call = True

            # Create completely fresh session
            cmd = self._create_new_session_command(enhanced_input, app_codebase_dir)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode == 0:
                logger.info("Fresh session recovery succeeded")
                return result
            else:
                logger.error(f"Fresh session recovery failed: {result.stderr}")

        except Exception as e:
            logger.error(f"Fresh session recovery failed: {e}")

        # All recovery strategies failed
        logger.error("All session recovery strategies failed")
        return None

    # === Session Lifecycle Management Methods ===

    def monitor_session_completion(self, output_text: str) -> bool:
        """
        Monitor session output for FinalSubmissionCommand completion signal.

        Args:
            output_text: Latest output from the session

        Returns:
            True if FinalSubmissionCommand is found
        """
        # Check if FinalSubmissionCommand appears anywhere in the output
        if "FinalSubmissionCommand" in output_text:
            logger.info("Found FinalSubmissionCommand completion signal")
            return True

        return False

    def cleanup_session(self):
        """
        Clean up session resources and reset state.
        Deletes both run-specific tracking files and Codex session files.
        """
        logger.info(f"Cleaning up session: {self.session_id}")

        try:
            # Delete the actual Codex session file from ~/.codex/sessions
            if self.session_file and os.path.exists(self.session_file):
                try:
                    os.remove(self.session_file)
                    logger.info(f"Deleted Codex session file: {self.session_file}")
                except Exception as e:
                    logger.warning(
                        f"Failed to delete Codex session file {self.session_file}: {e}"
                    )

            # Delete run-specific session tracking file
            run_session_file = self._get_run_session_file()
            if os.path.exists(run_session_file):
                os.remove(run_session_file)
                logger.info(f"Deleted run session file: {run_session_file}")

            # Clean up any other run session files (in case of orphaned files)
            import glob

            orphaned_files = glob.glob("/tmp/codex_run_session_*.txt")
            for file in orphaned_files:
                try:
                    os.remove(file)
                    logger.info(f"Cleaned up orphaned session file: {file}")
                except Exception as e:
                    logger.warning(f"Failed to clean up {file}: {e}")

        except Exception as e:
            logger.warning(f"Error during session cleanup: {e}")

        # Reset session state
        self.session_id = None
        self.session_file = None
        self.first_call = True

        logger.info("Session cleanup completed")

    def _create_error_result(
        self, stderr: str, execution_time: float
    ) -> CodexCLIResult:
        """Create a standardized error result."""
        return CodexCLIResult(
            success=False,
            output_text="",
            tool_outputs=[],
            execution_time=execution_time,
            stderr=stderr,
            session_id=self.session_id,
            session_file=self.session_file,
        )

    def _retry_with_backoff(self, func, max_retries: int = 3, base_delay: float = 1.0):
        """
        Retry a function with exponential backoff.

        Args:
            func: Function to retry
            max_retries: Maximum number of retry attempts
            base_delay: Base delay in seconds

        Returns:
            Function result if successful

        Raises:
            Exception: Last exception if all retries fail
        """
        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                return func()
            except Exception as e:
                last_exception = e
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"Attempt {attempt + 1} failed: {e}. Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.error(f"All {max_retries + 1} attempts failed")

        raise last_exception

    def call(
        self,
        input_text: str,
        mcp_config: dict,
        timeout_ms: int = 600_000,
    ) -> CodexCLIResult:
        """
        Execute Codex CLI with session management and secure localhost MCP server integration.
        Leverages Codex CLI's built-in session resumption for conversation continuity and prompt caching.

        Args:
            input_text: The prompt/input for Codex
            mcp_config: Secure localhost MCP server configuration
            timeout_ms: Timeout in milliseconds

        Returns:
            CodexCLIResult with execution results and session information
        """
        start_time = time.time()

        try:
            # Get app codebase directory from config
            app_codebase_dir = (
                mcp_config.get("app_codebase_dir", "/tmp") if mcp_config else "/tmp"
            )

            # Configure MCP server connection (secure container networking)
            if mcp_config and mcp_config.get("server_url"):
                server_url = mcp_config["server_url"]
                # Allow localhost, 127.0.0.1, and mcp-server (container networking)
                allowed_hosts = ["localhost", "127.0.0.1", "mcp-server"]
                if not any(host in server_url for host in allowed_hosts):
                    logger.warning(
                        f"Rejecting non-secure MCP server for security: {server_url}"
                    )
                    return self._create_error_result(
                        "Security policy: Only secure MCP servers allowed (localhost/mcp-server)",
                        time.time() - start_time,
                    )
                logger.info(
                    f"Using MCP proxy to connect to secure server: {server_url}"
                )

            # Prepare input without enhancement
            timeout_seconds = timeout_ms / 1000
            enhanced_input = input_text

            # Execute with robust error handling and recovery
            def _execute_with_recovery():
                # Determine whether to create new session or resume existing one
                if self._should_resume_session():
                    cmd = self._create_resume_session_command(
                        enhanced_input, app_codebase_dir
                    )
                    logger.info("Resuming Codex CLI session with localhost MCP")
                else:
                    cmd = self._create_new_session_command(
                        enhanced_input, app_codebase_dir
                    )
                    logger.info("Creating new Codex CLI session with localhost MCP")

                # Execute the Codex CLI command
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )

                # Check for session-specific failures
                if result.returncode != 0 and self._should_resume_session():
                    # Session resume failed, try recovery
                    logger.warning("Session resume failed, attempting recovery")
                    recovery_result = self._handle_session_failure(
                        Exception(f"Session resume failed: {result.stderr}"),
                        app_codebase_dir,
                        enhanced_input,
                    )
                    if recovery_result:
                        result = recovery_result
                    # If recovery still fails, result will have the original error

                return result

            # Execute with retry logic for transient failures
            try:
                result = self._retry_with_backoff(
                    _execute_with_recovery, max_retries=2, base_delay=2.0
                )
            except Exception as e:
                # If all retries fail, create an error result
                execution_time = time.time() - start_time
                logger.error(f"Codex CLI execution failed after all retries: {e}")
                return self._create_error_result(
                    f"Execution failed after retries: {str(e)}", execution_time
                )

            # Update session information after successful execution
            if result.returncode == 0:
                self._update_session_info_from_output()
                # Mark that we've completed the first call
                if self.first_call:
                    self.first_call = False

            execution_time = time.time() - start_time

            if result.returncode == 0:
                # Parse tool outputs if available (simple parsing)
                tool_outputs = []
                if "adb" in result.stdout.lower() or "command" in result.stdout.lower():
                    # Extract command-like interactions from output
                    lines = result.stdout.split("\n")
                    for line in lines:
                        if any(
                            keyword in line.lower()
                            for keyword in ["adb", "curl", "nmap", "executed"]
                        ):
                            tool_outputs.append(line.strip())

                # Log tool interactions for review
                if tool_outputs:
                    tool_logger.info(
                        f"Tool interactions detected ({len(tool_outputs)} items)"
                    )
                    for i, output in enumerate(tool_outputs, 1):
                        tool_logger.info(f"Tool {i}: {output}")

                # Log the full output
                tool_logger.info(
                    f"Codex execution completed. Output length: {len(result.stdout)} chars"
                )
                tool_logger.info(f"Full output:\n{result.stdout}")

                return CodexCLIResult(
                    success=True,
                    output_text=result.stdout,
                    tool_outputs=tool_outputs,
                    execution_time=execution_time,
                    stderr=result.stderr if result.stderr else None,
                    session_id=self.session_id,
                    session_file=self.session_file,
                )
            else:
                logger.error(f"Codex CLI failed with exit code {result.returncode}")
                logger.error(f"Stderr: {result.stderr}")

                # Provide helpful error messages for common issues
                if "No such device or address" in str(result.stderr):
                    auth_error = "Codex CLI authentication required. Please run 'codex login' to authenticate before using the codex agent."
                    logger.error(auth_error)
                    return self._create_error_result(auth_error, execution_time)
                elif "OPENAI_API_KEY" in str(result.stderr):
                    api_key_error = (
                        "Codex CLI requires OPENAI_API_KEY environment variable. "
                        "Please set it in agent/.env file or load it: export $(cat agent/.env | xargs)"
                    )
                    logger.error(api_key_error)
                    return self._create_error_result(api_key_error, execution_time)

                return self._create_error_result(result.stderr, execution_time)

        except subprocess.TimeoutExpired:
            execution_time = time.time() - start_time
            logger.error(f"Codex CLI execution timed out after {execution_time:.1f}s")
            return self._create_error_result("Execution timed out", execution_time)
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Codex CLI execution failed: {e}")
            return self._create_error_result(str(e), execution_time)
