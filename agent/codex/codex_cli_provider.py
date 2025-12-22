#!/usr/bin/env python3

import json
import logging
import os
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

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
    session_id: Optional[str] = None
    turns: int = 0


class CodexCLIProvider:
    """
    Codex CLI provider with session ID-based resumption.

    Each instance tracks its Codex session ID to ensure:
    - Parallel execution safety (each instance has its own session ID)
    - Proper session resumption across turns using `codex resume <session-id>`
    - Clean isolation between sessions
    - Integration with Codex CLI's native session management
    """

    def __init__(self):
        """
        Initialize the Codex CLI provider.
        """
        self.codex_binary = "codex"
        self.container_name = "kali-container"
        self.session_id = None  # Track the Codex session ID for resumption

    def validate(self) -> bool:
        """Validate that Codex CLI is available and accessible."""
        try:
            # Check if container is running first
            container_check = subprocess.run(
                ["docker", "ps", "-q", "-f", f"name={self.container_name}"],
                capture_output=True,
                text=True,
            )
            if not container_check.stdout.strip():
                logger.error(f"Container {self.container_name} is not running")
                return False

            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    self.container_name,
                    self.codex_binary,
                    "--version",
                ],
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
        timeout_ms: int = 1_200_000,
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
            timeout_ms: Timeout in milliseconds for entire execution
            max_iterations: Maximum number of turns to execute

        Returns:
            CodexCLIResult with execution results
        """
        start_time = time.time()

        try:
            # Get configuration
            # Default to /app/codebase inside container if not specified
            app_codebase_dir = "/app/codebase"

            # Check if this is a new session or resuming existing one
            is_new_session = self.session_id is None

            if is_new_session:
                logger.info("🚀 Starting new session")
            else:
                logger.info(f"🔄 Resuming existing session: {self.session_id}")

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

                logger.info(
                    f"✅ Turn {turn_count} completed in {result.execution_time:.1f}s"
                )
                logger.info(f"Output: {final_output}")

                # If output is empty, session might be done
                if not final_output.strip():
                    logger.info("Empty output received, assuming session complete")
                    break

            total_time = time.time() - start_time
            logger.info(f"🏁 Completed {turn_count} turns in {total_time:.1f}s")

            # Log final output
            tool_logger.info(f"Multi-turn execution completed. Turns: {turn_count}")
            tool_logger.info(f"Final output length: {len(final_output)} chars")
            tool_logger.info(f"Full output:\n{final_output}")

            return CodexCLIResult(
                success=True,
                output_text=final_output,
                tool_outputs=all_tool_outputs,
                execution_time=total_time,
                session_id=self.session_id,
                turns=turn_count,
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
                session_id=self.session_id,
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
                session_id=self.session_id,
            )

    def _run_codex_turn(
        self,
        prompt: str,
        app_codebase_dir: str,
        timeout_ms: int,
        is_initial: bool,
    ) -> CodexCLIResult:
        """
        Run a single Codex turn (either initial exec or resume) inside the container.

        Args:
            prompt: Initial prompt for exec
            app_codebase_dir: Working directory inside container
            timeout_ms: Timeout in milliseconds
            is_initial: True for new session, False for resume

        Returns:
            CodexCLIResult with turn results
        """
        turn_start = time.time()

        # Create temp file for JSONL output on host
        jsonl_file = tempfile.NamedTemporaryFile(
            mode="w+", suffix=".jsonl", delete=False
        )

        # Generate a unique path for output inside the container
        container_output_path = f"/tmp/codex_output_{uuid.uuid4()}.txt"

        try:
            # Construct the base docker exec command
            # We inject PYTHONUNBUFFERED=1 to ensure Python flushing if codex is Python-based
            cmd = [
                "docker",
                "exec",
                "-i",
                "-e",
                "PYTHONUNBUFFERED=1",
                self.container_name,
            ]

            # Use stdbuf to force line buffering for real-time visibility
            # This is critical because docker exec is non-interactive and defaults to block buffering
            cmd.extend(["stdbuf", "-oL", "-eL", self.codex_binary])

            # Note: API keys are now injected into the container environment by runner.py
            # So we don't need to pass them explicitly via -e here.

            if is_initial:
                # Build codex exec command for new session
                cmd.extend(
                    [
                        "exec",
                        "--dangerously-bypass-approvals-and-sandbox",
                        "--skip-git-repo-check",
                        "--json",
                        "-o",
                        container_output_path,
                        "-C",
                        app_codebase_dir,
                        prompt,
                    ]
                )
                logger.info(f"Executing new session in container: {' '.join(cmd)}")
            else:
                # Build codex exec command with experimental_resume to continue session
                # Find the session file for our session_id inside the container
                session_file_path = self._find_session_file(self.session_id)
                if not session_file_path:
                    raise Exception(
                        f"Could not find session file for ID: {self.session_id} in container"
                    )

                cmd.extend(
                    [
                        "-c",
                        f"experimental_resume={session_file_path}",
                        "exec",
                        "--dangerously-bypass-approvals-and-sandbox",
                        "--skip-git-repo-check",
                        "--json",
                        "-o",
                        container_output_path,
                        "-C",
                        app_codebase_dir,
                        prompt,  # Empty prompt to continue usually, checks logic below
                    ]
                )
                # TODO Remove session logic - is no longer needed
                logger.info(
                    f"Resuming session {self.session_id} from: {session_file_path}"
                )

            # Execute command
            # Execute command with streaming and strict timeout
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
                universal_newlines=True,
            )

            import selectors

            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            selector.register(process.stderr, selectors.EVENT_READ)

            stderr_output = []

            with open(jsonl_file.name, "w") as jsonl_out:
                start_time = time.time()
                while True:
                    # 1. Enforce Absolute Timeout
                    if time.time() - start_time > (timeout_ms / 1000):
                        process.kill()
                        selector.close()
                        raise subprocess.TimeoutExpired(cmd, timeout_ms / 1000)

                    # 2. Monitor I/O with short interval to allow timeout checks
                    # Wait max 0.1s for data
                    events = selector.select(timeout=0.1)

                    for key, mask in events:
                        fileobj = key.fileobj
                        line = fileobj.readline()

                        if fileobj == process.stdout:
                            if line:
                                # Write to file for later processing
                                jsonl_out.write(line)
                                jsonl_out.flush()

                                # Parse and log for real-time visibility
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
                                            preview = (
                                                content[:200] + "..."
                                                if len(content) > 200
                                                else content
                                            )
                                            logger.info(f"[Codex Message] {preview}")
                                except json.JSONDecodeError:
                                    if line.strip():
                                        logger.info(f"[Codex Raw] {line.strip()}")
                            else:
                                # EOF on stdout
                                selector.unregister(process.stdout)

                        elif fileobj == process.stderr:
                            if line:
                                stderr_output.append(line)
                            else:
                                # EOF on stderr
                                selector.unregister(process.stderr)

                    # 3. Check exit condition
                    # Only exit if process is dead AND our pipes are drained (unregistered)
                    if process.poll() is not None:
                        # Process ended, but are pipes empty?
                        # If selector keys are empty, we are done reading
                        if not selector.get_map():
                            break

            selector.close()
            returncode = process.poll()
            stderr_content = "".join(stderr_output)

            # Create a result object similar to subprocess.run structure
            result = type(
                "obj", (object,), {"returncode": returncode, "stderr": stderr_content}
            )

            execution_time = time.time() - turn_start

            # Read JSONL output
            with open(jsonl_file.name, "r") as f:
                jsonl_content = f.read()

            # Retrieve text output from container
            final_output = ""
            cp_result = subprocess.run(
                [
                    "docker",
                    "cp",
                    f"{self.container_name}:{container_output_path}",
                    "-",  # output to stdout
                ],
                capture_output=True,
                text=True,
            )

            if cp_result.returncode == 0:
                final_output = cp_result.stdout
            else:
                # If the command failed, the output file might not exist or be empty
                logger.warning(
                    f"Failed to retrieve output file from container: {cp_result.stderr}"
                )

            # Cleanup container output file
            subprocess.run(
                [
                    "docker",
                    "exec",
                    self.container_name,
                    "rm",
                    "-f",
                    container_output_path,
                ],
                capture_output=True,
                check=False,
            )

            # Parse JSONL events to extract tool outputs and session ID
            tool_outputs = []
            for line in jsonl_content.strip().split("\n"):
                if line:
                    try:
                        event = json.loads(line)
                        event_type = event.get("type")

                        # Extract session ID from thread.started event on initial run
                        if is_initial and event_type == "thread.started":
                            self.session_id = event.get("thread_id")
                            logger.info(f"Captured session ID: {self.session_id}")

                        if event_type == "tool_result":
                            tool_outputs.append(json.dumps(event.get("content", {})))
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse JSONL line: {e}")
                        continue

            if is_initial and not self.session_id:
                logger.warning("Could not capture session ID from initial execution")

            if result.returncode == 0:

                return CodexCLIResult(
                    success=True,
                    output_text=final_output,
                    tool_outputs=tool_outputs,
                    execution_time=execution_time,
                    session_id=self.session_id,
                )
            else:
                logger.error(f"Codex turn failed with code {result.returncode}")
                logger.error(f"stderr: {result.stderr}")

                # Provide helpful error messages
                if "No such device or address" in str(result.stderr):
                    auth_error = (
                        "Codex CLI authentication required. Please run 'codex login'"
                    )
                    logger.error(auth_error)
                    return CodexCLIResult(
                        success=False,
                        output_text=final_output,
                        tool_outputs=tool_outputs,
                        execution_time=execution_time,
                        stderr=auth_error,
                        session_id=self.session_id,
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
                        session_id=self.session_id,
                    )

                return CodexCLIResult(
                    success=False,
                    output_text=final_output,
                    tool_outputs=tool_outputs,
                    execution_time=execution_time,
                    stderr=result.stderr,
                    session_id=self.session_id,
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
                session_id=self.session_id,
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
                session_id=self.session_id,
            )
        finally:
            # Cleanup temp files
            jsonl_file.close()
            try:
                os.unlink(jsonl_file.name)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp files: {e}")

    def _find_session_file(self, session_id: str) -> Optional[str]:
        """
        Find the session file path for a given session ID inside the container.

        Args:
            session_id: The session ID to find

        Returns:
            Full path to session file inside container, or None if not found
        """
        try:
            # Calculate date-based path components
            # Session files are stored in ~/.codex/sessions/YYYY/MM/DD/
            # We need to find where ~ maps to in the container.
            # Assuming root, it's /root/.codex/sessions...
            # But let's try to just use `find` command to be sure or check both /root and /home/kali

            # Simple approach: Search in likely locations
            # The pattern is rollout-*-<session_id>.jsonl
            search_pattern = f"rollout-*-{session_id}.jsonl"

            # Construct find command
            # We search in /root/.codex and /home/kali/.codex just in case
            find_cmd = [
                "docker",
                "exec",
                self.container_name,
                "find",
                "/root/.codex/sessions",
                "/home/kali/.codex/sessions",
                "-name",
                search_pattern,
            ]

            result = subprocess.run(find_cmd, capture_output=True, text=True)

            if result.returncode == 0 and result.stdout.strip():
                # Take the first match
                first_match = result.stdout.strip().split("\n")[0]
                return first_match

            logger.warning(
                f"Session file not found for ID: {session_id} inside container"
            )
            return None

        except Exception as e:
            logger.error(f"Error finding session file: {e}")
            return None

    def cleanup(self):
        """
        Clean up session.

        Note: Codex CLI manages session files in its default location.
        This method is kept for API compatibility but no longer performs file cleanup.
        """
        if self.session_id:
            logger.info(
                f"Session {self.session_id} completed. "
                f"Codex CLI manages session file cleanup automatically."
            )
        else:
            logger.info("No session to clean up")

    def get_session_info(self) -> dict:
        """
        Get information about the current session.

        Returns:
            dict: Session metadata including session ID
        """
        return {
            "session_id": self.session_id,
            "has_session": self.session_id is not None,
        }
