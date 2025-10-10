#!/usr/bin/env python3
"""
Minimal Codex Agent for Mobile Security Testing

A clean, focused implementation that uses Codex CLI for mobile application
security testing while maintaining compatibility with the existing infrastructure.
"""

import os
import signal
import sys
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from agent.codex.codex_cli_provider import CodexCLIProvider
from agent.prompts.prompts import (
    APP_SERVER_ACCESS,
    BASE_EXAMPLES,
    BASE_INSTRUCTIONS,
    BASE_RESPONSE_FORMAT,
    DETECT_DESCRIPTION,
    SEPARATOR,
    STOP_TOKEN,
    SUBMISSION_INSTRUCTIONS,
    TARGET_HOST_EXAMPLE,
)
from utils.logger import logger, logger_manager
from utils.mcp_utils import get_mcp_server_config


class CodexAgent:
    """
    Minimal Codex agent for mobile security testing.

    Uses Codex CLI with MCP server integration to conduct comprehensive
    security assessments of Android applications.
    """

    def __init__(
        self,
        max_iterations: int = 30,
        screenshot_enabled: bool = False,
        app_name: str = "",
        dry_run: bool = False,
        app_server: Optional[str] = None,
        timeout_ms: int = 600_000,
        mcp_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize the Codex agent.

        Args:
            max_iterations: Maximum number of analysis iterations
            screenshot_enabled: Whether screenshot capability is available
            app_name: Name of the mobile application being tested
            dry_run: If True, skip actual execution for testing
            app_server: Optional app server URL for network testing
            timeout_ms: Timeout for Codex CLI calls in milliseconds
            mcp_config: MCP server configuration (auto-discovered if None)
        """
        self.max_iterations = max_iterations
        self.screenshot_enabled = screenshot_enabled
        self.app_name = app_name
        self.dry_run = dry_run
        self.app_server = app_server
        self.timeout_ms = timeout_ms

        # Load environment variables
        agent_dir = os.path.dirname(os.path.abspath(__file__))
        env_file = os.path.join(agent_dir, ".env")
        if os.path.exists(env_file):
            load_dotenv(env_file, override=True)

        # Initialize MCP configuration
        try:
            self.mcp_config = mcp_config or get_mcp_server_config()
        except Exception as e:
            logger.warning(f"Failed to get MCP config: {e}")
            self.mcp_config = {}

        # Initialize Codex CLI provider
        self.provider = CodexCLIProvider()

        # Set up signal handler for graceful cleanup on Ctrl-C
        signal.signal(signal.SIGINT, self._signal_handler)

        # Validate provider unless in dry run mode
        if not dry_run:
            if not self.provider.validate():
                raise RuntimeError(
                    "Codex CLI validation failed. Please ensure Codex CLI is installed and accessible."
                )

        # Initialize state
        self.conversation_history = []
        self.current_iteration = 0

        # Use shared logger's file name for consistency
        self.log_file = logger_manager.get_log_file_name()

        # Log initialization
        self._log_section(
            "CODEX AGENT INITIALIZED",
            [
                f"App: {app_name}",
                f"Max Iterations: {max_iterations}",
                f"Screenshot Enabled: {screenshot_enabled}",
                f"App Server: {app_server or 'None'}",
                f"Dry Run: {dry_run}",
                f"MCP Server: {self.mcp_config.get('server_url', 'Not configured')}",
            ],
        )

    def run(self) -> Dict[str, Any]:
        """
        Execute the mobile security testing analysis.

        Returns:
            Dictionary with execution results and metadata
        """
        logger.info("Starting Codex Agent execution...")

        if self.dry_run:
            logger.info("DRY RUN MODE - No actual Codex CLI execution")
            return self._create_dry_run_result()

        try:
            # Generate initial security testing prompt using standardized components
            initial_prompt = self._build_initial_prompt()

            # Execute main analysis loop
            return self._execute_analysis_loop(initial_prompt)

        except Exception as e:
            logger.error(f"Codex Agent execution failed: {e}")
            return self._create_result("error", str(e))

    def _execute_analysis_loop(self, initial_prompt: str) -> Dict[str, Any]:
        """Execute session-based analysis leveraging Codex CLI's built-in session management."""

        try:
            # Phase 1: Start persistent session with initial prompt
            self._log_section("STARTING PERSISTENT CODEX CLI SESSION")
            self._log_content("INITIAL PROMPT", initial_prompt)

            # Start persistent session (reset state for fresh start)
            self.provider.session_id = None
            self.provider.session_file = None
            self.provider.first_call = True

            logger.info("Starting new persistent Codex CLI session")
            result = self.provider.call(
                input_text=initial_prompt,
                mcp_config=self.mcp_config,
                timeout_ms=self.timeout_ms,
            )

            if not result.success:
                logger.error(f"Failed to start persistent session: {result.stderr}")
                return self._create_result("error", result.stderr)

            self.current_iteration = 1

            # Log initial response
            self._log_content("SESSION STARTED", result.output_text)

            # Add to conversation history
            self._add_to_history(initial_prompt, result)

            # Check if analysis completed in first iteration
            if self.provider.monitor_session_completion(result.output_text):
                logger.info("Analysis completed in initial session")
                return self._create_result("completed")

            # Phase 2: Session continuation with automatic context management
            for iteration in range(2, self.max_iterations + 1):
                self.current_iteration = iteration
                logger.info(
                    f"{'=' * 20} CONTINUATION {self.current_iteration}/{self.max_iterations} {'=' * 20}"
                )

                # Send simple continuation prompt - let Codex CLI handle context
                continuation_prompt = self._get_continuation_prompt()
                self._log_content("CONTINUATION PROMPT", continuation_prompt)

                # Send continuation to existing session
                if not self._validate_session("continuation"):
                    break

                logger.info(
                    f"Sending continuation to session {self.provider.session_id}"
                )
                result = self.provider.call(
                    input_text=continuation_prompt,
                    mcp_config=self.mcp_config,
                    timeout_ms=self.timeout_ms,
                )

                if not result.success:
                    logger.error(f"Session continuation failed: {result.stderr}")
                    break

                # Log response and tool interactions
                self._log_content("SESSION RESPONSE", result.output_text)
                if result.tool_outputs:
                    logger.info(
                        f"[TOOL INTERACTIONS - {len(result.tool_outputs)} outputs]"
                    )
                    for i, tool_output in enumerate(result.tool_outputs):
                        logger.info(f"Tool Output {i + 1}: {tool_output}")
                    logger.info("-" * 40)

                # Add to conversation history
                self._add_to_history(continuation_prompt, result)

                # Check if analysis is complete using session-aware completion detection
                if self.provider.monitor_session_completion(result.output_text):
                    logger.info("Analysis completed based on session output")
                    break

                # If we're approaching max iterations, send conclusion prompt
                if iteration == self.max_iterations - 1:
                    logger.info("Approaching max iterations, requesting conclusion")
                    if self._validate_session("conclusion"):
                        logger.info(
                            f"Sending conclusion to session {self.provider.session_id}"
                        )
                        conclusion_text = "Please conclude your analysis and provide your final findings."
                        conclusion_result = self.provider.call(
                            input_text=conclusion_text,
                            mcp_config=self.mcp_config,
                            timeout_ms=self.timeout_ms,
                        )
                        if conclusion_result.success:
                            self._add_to_history(conclusion_text, conclusion_result)
                    break

            return self._create_result("completed")

        except Exception as e:
            logger.error(f"Session-based analysis failed: {e}")
            return self._create_result("error", str(e))
        finally:
            # Clean up session resources
            try:
                self.provider.cleanup_session()
            except Exception as e:
                logger.warning(f"Session cleanup warning: {e}")

    def _get_continuation_prompt(self) -> str:
        """Get continuation prompt (rotates through variety for context freshness)."""
        prompts = [
            "Continue your security analysis based on your previous findings.",
            "Please proceed with the next phase of your security assessment.",
            "Continue investigating any remaining security aspects.",
            "Please advance your analysis focusing on unexplored areas.",
        ]
        return prompts[(self.current_iteration - 2) % len(prompts)]

    def _validate_session(self, context: str) -> bool:
        """Validate that an active session exists."""
        if not self.provider.session_id:
            logger.error(f"No active session for {context}")
            return False
        return True

    def _add_to_history(self, input_text: str, result: Any) -> None:
        """Add interaction to conversation history."""
        self.conversation_history.append(
            {
                "iteration": self.current_iteration,
                "input": input_text,
                "output": result.output_text,
                "tool_outputs": result.tool_outputs,
                "execution_time": result.execution_time,
                "session_id": result.session_id,
                "session_file": result.session_file,
            }
        )

    def _log_section(self, title: str, details: list = None) -> None:
        """Log a section with consistent formatting."""
        logger.info("=" * 80)
        logger.info(title)
        logger.info("=" * 80)
        if details:
            for detail in details:
                logger.info(detail)
            logger.info("=" * 80)

    def _log_content(self, label: str, content: str) -> None:
        """Log content with label and character count."""
        logger.info(f"[{label} - {len(content)} chars]")
        logger.info(content)
        logger.info("-" * 40)

    def _create_result(self, status: str, error: str = None) -> Dict[str, Any]:
        """Create result dictionary with common structure."""
        result = {
            "status": status,
            "turns": self.current_iteration,
            "final_message": (
                self.conversation_history[-1]["output"]
                if self.conversation_history and status == "completed"
                else None
            ),
            "log_file": self.log_file,
            "conversation_history": self.conversation_history,
        }

        if error:
            result["error"] = error

        if status == "completed":
            logger.info(f"{'=' * 20} SESSION-BASED ANALYSIS COMPLETED {'=' * 20}")
            logger.info(f"Status: Completed after {self.current_iteration} iterations")
            logger.info(f"Total iterations: {self.current_iteration}")
            logger.info(f"Log file: {self.log_file}")

        return result

    def _build_initial_prompt(self) -> str:
        """Build the initial security testing prompt using standardized components from prompts.py."""
        # Build base prompt using DETECT_DESCRIPTION directly
        prompt_parts = [
            DETECT_DESCRIPTION,
        ]

        # Add app server information if provided (same as custom agent)
        if self.app_server:
            prompt_parts.extend(
                [SEPARATOR, APP_SERVER_ACCESS.format(app_server=self.app_server)]
            )

        # Add standardized components (same as custom agent)
        prompt_parts.extend(
            [
                SEPARATOR,
                BASE_RESPONSE_FORMAT.format(stop_token=STOP_TOKEN),
                SEPARATOR,
                BASE_INSTRUCTIONS.format(stop_token=STOP_TOKEN),
                SEPARATOR,
                BASE_EXAMPLES.format(stop_token=STOP_TOKEN),
            ]
        )

        # Add target host example if provided (same as custom agent)
        if self.app_server:
            prompt_parts.extend(
                [
                    SEPARATOR,
                    TARGET_HOST_EXAMPLE.format(
                        resolved_host=self.app_server, stop_token=STOP_TOKEN
                    ),
                ]
            )

        prompt_parts.extend([SEPARATOR, SUBMISSION_INSTRUCTIONS])

        return "".join(prompt_parts)

    def _create_dry_run_result(self) -> Dict[str, Any]:
        """Create a mock result for dry run mode."""
        return {
            "status": "dry_run_completed",
            "turns": 0,
            "final_message": f"DRY RUN: Codex Agent configured for {self.app_name}",
            "log_file": self.log_file,
            "mcp_config": self.mcp_config,
            "app_name": self.app_name,
        }

    def _signal_handler(self, _sig, _frame):
        """Handle Ctrl-C (SIGINT) for graceful cleanup."""
        logger.info("\nCtrl-C received, performing session cleanup...")
        try:
            self.provider.cleanup_session()
            logger.info("Session cleanup completed")
        except Exception as e:
            logger.warning(f"Session cleanup warning: {e}")
        sys.exit(0)
