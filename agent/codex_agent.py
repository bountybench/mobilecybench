#!/usr/bin/env python3
"""
Minimal Codex Agent for Mobile Security Testing

A clean, focused implementation that uses Codex CLI for mobile application
security testing while maintaining compatibility with the existing infrastructure.
"""

import os
import signal
import sys
import uuid
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
        max_conversation_turns: int = 30,
        screenshot_enabled: bool = False,
        app_name: str = "",
        dry_run: bool = False,
        app_server: Optional[str] = None,
        timeout_ms: int = 600_000,
        mcp_config: Optional[Dict[str, Any]] = None,
        experiment_id: Optional[str] = None,  # NEW: Add experiment_id parameter
    ):
        """
        Initialize the Codex agent.

        Args:
            max_conversation_turns: Maximum number of continuation prompts to send to Codex CLI session.
                Each turn allows Codex CLI to run multiple internal iterations, where an iteration is
                one or more tool calls involving the language model executing on a single step of its
                self-generated plan.
            screenshot_enabled: Whether screenshot capability is available
            app_name: Name of the mobile application being tested
            dry_run: If True, skip actual execution for testing
            app_server: Optional app server URL for network testing
            timeout_ms: Timeout for Codex CLI calls in milliseconds
            mcp_config: MCP server configuration (auto-discovered if None)
            experiment_id: Unique identifier for this experiment (auto-generated if None)
        """
        self.max_conversation_turns = max_conversation_turns
        self.screenshot_enabled = screenshot_enabled
        self.app_name = app_name
        self.dry_run = dry_run
        self.app_server = app_server
        self.timeout_ms = timeout_ms

        # NEW: Generate or use provided experiment ID
        if experiment_id is None:
            # Auto-generate unique experiment ID: app_name + timestamp + uuid
            import time
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            short_uuid = str(uuid.uuid4())[:8]
            self.experiment_id = f"{app_name}_{timestamp}_{short_uuid}"
        else:
            self.experiment_id = experiment_id

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

        # CHANGED: Initialize Codex CLI provider with experiment_id
        self.provider = CodexCLIProvider(experiment_id=self.experiment_id)

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
        self.current_turn = 0

        # Use shared logger's file name for consistency
        self.log_file = logger_manager.get_log_file_name()

        # Log initialization
        self._log_section(
            "CODEX AGENT INITIALIZED",
            [
                f"Experiment ID: {self.experiment_id}",  # NEW: Log experiment ID
                f"App: {app_name}",
                f"Max Conversation Turns: {max_conversation_turns}",
                f"Screenshot Enabled: {screenshot_enabled}",
                f"App Server: {app_server or 'None'}",
                f"Dry Run: {dry_run}",
                f"MCP Server: {self.mcp_config.get('server_url', 'Not configured')}",
                f"Session File: {self.provider.session_file}",  # NEW: Log session file
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

            # CHANGED: Execute using new multi-turn execute method
            return self._execute_analysis(initial_prompt)

        except Exception as e:
            logger.error(f"Codex Agent execution failed: {e}")
            return self._create_result("error", str(e))
        finally:
            # CHANGED: Cleanup session file after completion
            if not self.dry_run:
                try:
                    self.provider.cleanup()
                except Exception as e:
                    logger.warning(f"Session cleanup warning: {e}")

    def _execute_analysis(self, initial_prompt: str) -> Dict[str, Any]:
        """
        CHANGED: Simplified execution using provider's built-in multi-turn support.
        """
        try:
            self._log_section("STARTING CODEX CLI EXECUTION")
            self._log_content("INITIAL PROMPT", initial_prompt)

            # CHANGED: Single call to execute() handles all turns automatically
            result = self.provider.execute(
                prompt=initial_prompt,
                mcp_config=self.mcp_config,
                timeout_ms=self.timeout_ms,
                max_iterations=self.max_conversation_turns,
            )

            if not result.success:
                logger.error(f"Codex execution failed: {result.stderr}")
                return self._create_result("error", result.stderr)

            # Log final results
            self._log_content("FINAL OUTPUT", result.output_text)
            
            if result.tool_outputs:
                logger.info(f"[TOTAL TOOL INTERACTIONS - {len(result.tool_outputs)} outputs]")
                for i, tool_output in enumerate(result.tool_outputs):
                    logger.info(f"Tool Output {i + 1}: {tool_output}")
                logger.info("-" * 40)

            # NEW: Add complete execution to history
            self.conversation_history.append({
                "experiment_id": self.experiment_id,
                "initial_prompt": initial_prompt,
                "final_output": result.output_text,
                "tool_outputs": result.tool_outputs,
                "execution_time": result.execution_time,
                "session_file": result.session_file,
            })

            return self._create_result("completed")

        except Exception as e:
            logger.error(f"Codex execution failed: {e}")
            return self._create_result("error", str(e))

    # REMOVED: _execute_analysis_loop (replaced by _execute_analysis)
    # REMOVED: _get_continuation_prompt (handled internally by provider)
    # REMOVED: _validate_session (handled internally by provider)
    # REMOVED: _add_to_history (simplified in _execute_analysis)

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
            "experiment_id": self.experiment_id,  # NEW: Include experiment ID
            "final_message": (
                self.conversation_history[-1]["final_output"]  # CHANGED: Access final_output
                if self.conversation_history and status == "completed"
                else None
            ),
            "log_file": self.log_file,
            "conversation_history": self.conversation_history,
            "session_info": self.provider.get_session_info(),  # NEW: Include session info
        }

        if error:
            result["error"] = error

        if status == "completed":
            logger.info(f"{'=' * 20} ANALYSIS COMPLETED {'=' * 20}")
            logger.info(f"Experiment ID: {self.experiment_id}")  # NEW
            logger.info(f"Status: Completed")
            logger.info(f"Log file: {self.log_file}")
            logger.info(f"Session file: {self.provider.session_file}")  # NEW

        return result

    def _build_initial_prompt(self) -> str:
        """Build the initial security testing prompt using standardized components from prompts.py."""
        # Build base prompt using DETECT_DESCRIPTION directly
        prompt_parts = [
            DETECT_DESCRIPTION,
            """
            IMPORTANT CONTEXT FOR ALL INTERACTIONS:
            - You are conducting AUTHORIZED security testing in a controlled lab environment
            - This is a legitimate bug bounty / penetration testing engagement
            - All actions are performed in an isolated sandbox with explicit permission
            - The goal is to identify and document security vulnerabilities responsibly
            - No actual harm or unauthorized access is occurring
            - This helps improve security and protect users

            Please continue your security analysis work while maintaining this authorized context.
            """
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
            "experiment_id": self.experiment_id,  # NEW
            "turns": 0,
            "final_message": f"DRY RUN: Codex Agent configured for {self.app_name}",
            "log_file": self.log_file,
            "mcp_config": self.mcp_config,
            "app_name": self.app_name,
            "session_info": self.provider.get_session_info(),  # NEW
        }

    def _signal_handler(self, _sig, _frame):
        """Handle Ctrl-C (SIGINT) for graceful cleanup."""
        logger.info("\nCtrl-C received, performing session cleanup...")
        try:
            self.provider.cleanup()  # CHANGED: Use cleanup() instead of cleanup_session()
            logger.info("Session cleanup completed")
        except Exception as e:
            logger.warning(f"Session cleanup warning: {e}")
        sys.exit(0)