#!/usr/bin/env python3

import os
import signal
import sys
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from agent.agent_helpers import get_directory_tree
from agent.claude_code.claude_code_cli_provider import ClaudeCodeCLIProvider
from agent.prompts.prompts import build_detect_prompt, build_synthetic_prompt
from utils.logger import logger, logger_manager


class ClaudeCodeAgent:
    def __init__(
        self,
        app_name: str = "",
        dry_run: bool = False,
        app_server: Optional[str] = None,
        timeout_ms: int = 1_200_000,
        package_name: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        include_ssrf: bool = True,
        model: str = "sonnet",
        workflow: str = "discovery",
    ):
        """
        Initialize the Claude Code agent.

        Args:
            app_name: Name of the mobile application being tested
            dry_run: If True, skip actual execution for testing
            app_server: Optional app server URL for network testing
            timeout_ms: Timeout for Claude Code CLI calls in milliseconds
            package_name: Android package name for the app being tested
            username: Username for the app
            password: Password for the app
            include_ssrf: Whether to include SSRF instructions in the prompt
            model: Claude model to use (e.g. "sonnet", "opus", "haiku")
            workflow: Workflow type ("discovery" or "exploit")
        """
        self.app_name = app_name
        self.dry_run = dry_run
        self.app_server = app_server
        self.timeout_ms = timeout_ms
        self.package_name = package_name
        self.username = username
        self.password = password
        self.include_ssrf = include_ssrf
        self.model = model
        self.workflow = workflow

        # Load environment variables
        agent_dir = os.path.dirname(os.path.abspath(__file__))
        env_file = os.path.join(agent_dir, ".env")
        if os.path.exists(env_file):
            load_dotenv(env_file, override=True)

        # Get initial directory tree context
        self._initial_tree_context = get_directory_tree()

        self.provider = ClaudeCodeCLIProvider()

        # Set up signal handler for graceful cleanup on Ctrl-C
        signal.signal(signal.SIGINT, self._signal_handler)

        # Validate provider unless in dry run mode
        if not dry_run:
            if not self.provider.validate():
                raise RuntimeError(
                    "Claude Code CLI validation failed. "
                    "Please ensure Claude Code is installed and authenticated."
                )

        # Initialize state
        self.conversation_history = []
        self.current_turn = 0

        # Use shared logger's file name for consistency
        self.log_file = logger_manager.get_log_file_name()

        # Log initialization
        self._log_section(
            "AGENT CONFIGURATION",
            [
                "Agent: claude-code",
                f"App: {self.app_name}",
                f"Package: {self.package_name}",
                f"Model: {self.model}",
                f"Workflow: {self.workflow}",
                f"App Server: {app_server or 'None'}",
                f"Dry Run: {dry_run}",
            ],
        )

    def run(self) -> Dict[str, Any]:
        """
        Execute the mobile security testing analysis.

        Returns:
            Dictionary with execution results and metadata
        """
        logger.info("Starting Claude Code Agent execution...")

        if self.dry_run:
            logger.info("DRY RUN MODE - No actual Claude Code CLI execution")
            return self._create_dry_run_result()

        try:
            initial_prompt = self._get_default_system_prompt()
            return self._execute_analysis(initial_prompt)

        except Exception as e:
            logger.error(f"Claude Code Agent execution failed: {e}")
            return self._create_result("error", str(e))

    def _execute_analysis(self, initial_prompt: str) -> Dict[str, Any]:
        """Execute analysis using provider's built-in multi-turn support."""
        try:
            self._log_section("STARTING CLAUDE CODE CLI EXECUTION")
            self._log_content("INITIAL PROMPT", initial_prompt)

            result = self.provider.execute(
                prompt=initial_prompt,
                timeout_ms=self.timeout_ms,
                model=self.model,
            )

            if not result.success:
                logger.error(f"Claude Code execution failed: {result.stderr}")
                return self._create_result("error", result.stderr)

            # Log final results
            self._log_content("FINAL OUTPUT", result.output_text)

            if result.tool_outputs:
                logger.info(f"[TOOL CALLS DETECTED: {len(result.tool_outputs)}]")
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
                    "turns": result.turns,
                    "cost_usd": result.cost_usd,
                }
            )

            return self._create_result("completed", turns=result.turns)

        except Exception as e:
            logger.error(f"Claude Code execution failed: {e}")
            return self._create_result("error", str(e))

    def _get_default_system_prompt(self) -> str:
        """Build prompt based on workflow mode."""
        if self.workflow == "exploit":
            return build_synthetic_prompt(
                package_name=self.package_name,
                username=self.username,
                password=self.password,
                app_server=self.app_server,
            )
        else:
            # Strip port from app_server for hping3 example
            resolved_host = None
            if self.app_server:
                resolved_host = self.app_server.split(":")[0]

            return build_detect_prompt(
                package_name=self.package_name,
                codebase_tree=self._initial_tree_context,
                app_server=self.app_server,
                username=self.username,
                password=self.password,
                include_ssrf=self.include_ssrf,
                resolved_host=resolved_host,
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

    def _create_result(
        self, status: str, error: str = None, turns: int = 0
    ) -> Dict[str, Any]:
        """Create result dictionary with common structure."""
        result = {
            "agent_type": "claude-code",
            "status": status,
            "turns_taken": turns,
            "tool_call_count": 0,
            "unique_tools": [],
            "token_totals": {},
            "final_message": (
                self.conversation_history[-1]["final_output"]
                if self.conversation_history and status == "completed"
                else None
            ),
            "log_file": self.log_file,
            "conversation_file": None,
            "conversation_history": self.conversation_history,
        }

        if error:
            result["error"] = error

        if status == "completed":
            logger.info(f"{'=' * 20} ANALYSIS COMPLETED {'=' * 20}")
            logger.info("Status: Completed")
            logger.info(f"Turns: {turns}")
            logger.info(f"Log file: {self.log_file}")

        return result

    def _create_dry_run_result(self) -> Dict[str, Any]:
        """Create a mock result for dry run mode."""
        return {
            "agent_type": "claude-code",
            "status": "dry_run_completed",
            "turns_taken": 0,
            "tool_call_count": 0,
            "unique_tools": [],
            "token_totals": {},
            "final_message": f"DRY RUN: Claude Code Agent configured for {self.app_name}",
            "log_file": self.log_file,
            "conversation_file": None,
            "app_name": self.app_name,
        }

    def _signal_handler(self, _sig, _frame):
        """Handle Ctrl-C (SIGINT) for graceful cleanup."""
        logger.info("\nCtrl-C received, exiting...")
        sys.exit(0)
