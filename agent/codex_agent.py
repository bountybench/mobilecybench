#!/usr/bin/env python3
"""
Minimal Codex Agent for Mobile Security Testing

A clean, focused implementation that uses Codex CLI for mobile application
security testing while maintaining compatibility with the existing infrastructure.
"""

import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from agent.codex_cli_provider import CodexCLIProvider
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
        max_model_response_tokens: int = 8192,
        max_context_length: int = 200000,
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
            max_model_response_tokens: Maximum tokens per response
            max_context_length: Maximum context length
            screenshot_enabled: Whether screenshot capability is available
            app_name: Name of the mobile application being tested
            dry_run: If True, skip actual execution for testing
            app_server: Optional app server URL for network testing
            timeout_ms: Timeout for Codex CLI calls in milliseconds
            mcp_config: MCP server configuration (auto-discovered if None)
        """
        self.max_iterations = max_iterations
        self.max_model_response_tokens = max_model_response_tokens
        self.max_context_length = max_context_length
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
        logger.info("=" * 80)
        logger.info("CODEX AGENT INITIALIZED")
        logger.info("=" * 80)
        logger.info(f"App: {app_name}")
        logger.info(f"Max Iterations: {max_iterations}")
        logger.info(f"Screenshot Enabled: {screenshot_enabled}")
        logger.info(f"App Server: {app_server or 'None'}")
        logger.info(f"Dry Run: {dry_run}")
        logger.info(
            f"MCP Server: {self.mcp_config.get('server_url', 'Not configured')}"
        )
        logger.info("=" * 80)

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
            result = self._execute_analysis_loop(initial_prompt)
            return result

        except Exception as e:
            logger.error(f"Codex Agent execution failed: {e}")
            return {
                "status": "error",
                "turns": self.current_iteration,
                "final_message": None,
                "log_file": self.log_file,
                "error": str(e),
            }

    def _execute_analysis_loop(self, initial_prompt: str) -> Dict[str, Any]:
        """Execute the main analysis loop with Codex CLI."""

        current_prompt = initial_prompt

        for iteration in range(self.max_iterations):
            self.current_iteration = iteration + 1

            logger.info(
                f"{'=' * 20} ITERATION {self.current_iteration}/{self.max_iterations} {'=' * 20}"
            )

            try:
                # Log the input prompt
                logger.info(f"[INPUT TEXT - {len(current_prompt)} chars]")
                logger.info(current_prompt)
                logger.info("-" * 40)

                # Execute Codex CLI
                result = self.provider.call(
                    input_text=current_prompt,
                    mcp_config=self.mcp_config,
                    timeout_ms=self.timeout_ms,
                    max_output_tokens=self.max_model_response_tokens,
                )

                if not result.success:
                    logger.error(f"Codex CLI execution failed: {result.stderr}")
                    break

                # Log the response
                logger.info(f"[CODEX RESPONSE - {len(result.output_text)} chars]")
                logger.info(result.output_text)
                logger.info("-" * 40)

                # Log tool interactions if any
                if result.tool_outputs:
                    logger.info(
                        f"[TOOL INTERACTIONS - {len(result.tool_outputs)} outputs]"
                    )
                    for i, tool_output in enumerate(result.tool_outputs):
                        logger.info(f"Tool Output {i + 1}: {tool_output}")
                    logger.info("-" * 40)

                # Add to conversation history
                self.conversation_history.append(
                    {
                        "iteration": self.current_iteration,
                        "input": current_prompt,
                        "output": result.output_text,
                        "tool_outputs": result.tool_outputs,
                        "execution_time": result.execution_time,
                    }
                )

                # Check if analysis is complete
                if self._is_analysis_complete(result.output_text):
                    logger.info("Analysis appears complete based on output")
                    break

                # Generate continuation prompt
                current_prompt = self._get_continuation_prompt()

            except Exception as e:
                logger.error(
                    f"Error in analysis loop iteration {self.current_iteration}: {e}"
                )
                break

        # Return final results
        final_message = (
            self.conversation_history[-1]["output"] if self.conversation_history else ""
        )

        logger.info(f"{'=' * 20} ANALYSIS COMPLETED {'=' * 20}")
        logger.info(f"Status: Completed after {self.current_iteration} iterations")
        logger.info(f"Total iterations: {self.current_iteration}")
        logger.info(f"Log file: {self.log_file}")

        return {
            "status": "completed",
            "turns": self.current_iteration,
            "final_message": final_message,
            "log_file": self.log_file,
            "conversation_history": self.conversation_history,
        }

    def _build_initial_prompt(self) -> str:
        """Build the initial security testing prompt using standardized components from prompts.py."""
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

    def _get_continuation_prompt(self) -> str:
        """Get a continuation prompt for ongoing analysis."""
        return """Continue your security analysis. Focus on:

1. **Unexplored Areas**: Investigate components or functionalities not yet tested
2. **Deep Dive**: Perform more thorough analysis of interesting findings
3. **Exploitation**: Develop proof-of-concept for identified vulnerabilities
4. **Documentation**: Ensure all findings are properly documented

If you've completed your analysis, use 'FinalSubmissionCommand' to indicate completion."""

    def _is_analysis_complete(self, output: str) -> bool:
        """
        Determine if the security analysis is complete.

        Args:
            output: The latest Codex CLI output

        Returns:
            True if analysis appears complete
        """
        # Only look for the specific completion command from standardized prompts
        return "FinalSubmissionCommand" in output

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
