#!/usr/bin/env python3

import os
import signal
import sys
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from agent.agent_helpers import get_directory_tree
from agent.codex.codex_cli_provider import CodexCLIProvider
from agent.prompts.prompts import (
    AGENT_GOAL,
    APP_CREDENTIALS,
    APP_SERVER_ACCESS,
    BASE_EXAMPLES,
    BASE_INSTRUCTIONS,
    BASE_RESPONSE_FORMAT,
    DETECT_DESCRIPTION,
    SSRF_INSTRUCTIONS,
    SSRF_PROBE_HOST,
    SSRF_PROBE_PORT,
    STOP_TOKEN,
    TARGET_HOST_EXAMPLE,
)
from utils.logger import logger, logger_manager

# from utils.mcp_utils import get_mcp_server_config


class CodexAgent:
    """
    Codex agent for mobile security testing.

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
        timeout_ms: int = 1_200_000,
        mcp_config: Optional[Dict[str, Any]] = None,
        network_access: bool = True,
        package_name: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        include_ssrf: bool = True,
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
            network_access: Whether network access is available
            package_name: Android package name for the app being tested
            username: Username for the app
            password: Password for the app
            include_ssrf: Whether to include SSRF instructions in the prompt
        """
        self.max_conversation_turns = max_conversation_turns
        self.screenshot_enabled = screenshot_enabled
        self.app_name = app_name
        self.dry_run = dry_run
        self.app_server = app_server
        self.timeout_ms = timeout_ms
        self.network_access = network_access
        self.package_name = package_name
        self.username = username
        self.password = password
        self.include_ssrf = include_ssrf

        # Load environment variables
        agent_dir = os.path.dirname(os.path.abspath(__file__))
        env_file = os.path.join(agent_dir, ".env")
        if os.path.exists(env_file):
            load_dotenv(env_file, override=True)

        # Initialize MCP configuration
        self.mcp_config = mcp_config or {}

        # Get initial directory tree context
        self._initial_tree_context = get_directory_tree()

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
        self.current_turn = 0

        # Use shared logger's file name for consistency
        self.log_file = logger_manager.get_log_file_name()

        # Log initialization
        self._log_section(
            "CODEX AGENT INITIALIZED",
            [
                f"App: {app_name}",
                f"Max Conversation Turns: {max_conversation_turns}",
                f"Screenshot Enabled: {screenshot_enabled}",
                f"App Server: {app_server or 'None'}",
                f"Dry Run: {dry_run}",
                f"MCP Server: {self.mcp_config.get('server_url', 'Not configured')}",
                f"Session ID: {self.provider.session_id}",
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
            initial_prompt = self._get_default_system_prompt()

            # Execute using provider's multi-turn execute method
            return self._execute_analysis(initial_prompt)

        except Exception as e:
            logger.error(f"Codex Agent execution failed: {e}")
            return self._create_result("error", str(e))
        finally:
            # Cleanup session after completion
            if not self.dry_run:
                try:
                    self.provider.cleanup()
                except Exception as e:
                    logger.warning(f"Session cleanup warning: {e}")

    def _execute_analysis(self, initial_prompt: str) -> Dict[str, Any]:
        """
        Execute analysis using provider's built-in multi-turn support.
        """
        try:
            self._log_section("STARTING CODEX CLI EXECUTION")
            self._log_content("INITIAL PROMPT", initial_prompt)

            # Single call to execute() handles all turns automatically
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
                logger.info(
                    f"[TOTAL TOOL INTERACTIONS - {len(result.tool_outputs)} outputs]"
                )
                for i, tool_output in enumerate(result.tool_outputs):
                    logger.info(f"Tool Output {i + 1}: {tool_output}")
                logger.info("-" * 40)

            # Add complete execution to history
            self.conversation_history.append(
                {
                    "initial_prompt": initial_prompt,
                    "final_output": result.output_text,
                    "tool_outputs": result.tool_outputs,
                    "execution_time": result.execution_time,
                    "session_id": result.session_id,
                    "turns": result.turns,
                }
            )

            return self._create_result("completed", turns=result.turns)

        except Exception as e:
            logger.error(f"Codex execution failed: {e}")
            return self._create_result("error", str(e))

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

    def _create_result(
        self, status: str, error: str = None, turns: int = 0
    ) -> Dict[str, Any]:
        """Create result dictionary with common structure."""
        result = {
            "status": status,
            "turns": turns,
            "final_message": (
                self.conversation_history[-1]["final_output"]
                if self.conversation_history and status == "completed"
                else None
            ),
            "log_file": self.log_file,
            "conversation_history": self.conversation_history,
            "session_info": self.provider.get_session_info(),
        }

        if error:
            result["error"] = error

        if status == "completed":
            logger.info(f"{'=' * 20} ANALYSIS COMPLETED {'=' * 20}")
            logger.info("Status: Completed")
            logger.info(f"Turns: {turns}")
            logger.info(f"Log file: {self.log_file}")
            logger.info(f"Session ID: {self.provider.session_id}")

        return result

    def _get_default_system_prompt(self) -> str:
        prompt_parts = [
            DETECT_DESCRIPTION,
            AGENT_GOAL.format(
                package_name=self.package_name, codebase=self._initial_tree_context
            ),
        ]

        if self.network_access and self.app_server:
            prompt_parts.extend([APP_SERVER_ACCESS.format(app_server=self.app_server)])

        if self.username and self.password:
            prompt_parts.extend(
                [APP_CREDENTIALS.format(username=self.username, password=self.password)]
            )

        prompt_parts.extend(
            [
                BASE_RESPONSE_FORMAT.format(stop_token=STOP_TOKEN),
                BASE_INSTRUCTIONS.format(
                    stop_token=STOP_TOKEN,
                ),
            ]
        )

        if self.include_ssrf:
            prompt_parts.append(
                SSRF_INSTRUCTIONS.format(
                    ssrf_host=SSRF_PROBE_HOST,
                    ssrf_port=SSRF_PROBE_PORT,
                )
            )

        prompt_parts.append(BASE_EXAMPLES.format(stop_token=STOP_TOKEN))

        # Add target host example if provided
        if self.app_server:
            # Strip port from app_server for hping3 example as it doesn't support host:port syntax
            host_only = self.app_server.split(":")[0]
            prompt_parts.extend(
                [
                    TARGET_HOST_EXAMPLE.format(
                        resolved_host=host_only, stop_token=STOP_TOKEN
                    ),
                ]
            )

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
            "session_info": self.provider.get_session_info(),
        }

    def _signal_handler(self, _sig, _frame):
        """Handle Ctrl-C (SIGINT) for graceful cleanup."""
        logger.info("\nCtrl-C received, performing session cleanup...")
        try:
            self.provider.cleanup()
            logger.info("Session cleanup completed")
        except Exception as e:
            logger.warning(f"Session cleanup warning: {e}")
        sys.exit(0)
