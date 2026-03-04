"""Base workflow class defining the evaluation interface."""

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from models.config import RunnerConfig

logger = logging.getLogger(__name__)


class Workflow(ABC):
    """
    Abstract base class for evaluation workflows.

    Subclasses set ``self.agent_env`` during ``setup_runtime_environment()``.

    Each workflow defines how to:
    1. Validate arguments before starting
    2. Set up the runtime environment (emulator, APK, backend)
    3. Configure and initialize the agent
    4. Run the agent
    5. Evaluate the results
    6. Save artifacts and clean up
    """

    def __init__(self, config: RunnerConfig, app_name: str, project_root: Path):
        self.config = config
        self.app_name = app_name
        self.app_dir = project_root / "apps" / app_name
        self.project_root = project_root
        self.metadata: dict = {}
        self.emulator = None
        self.agent_env = None
        self.agent = None
        self.agent_result: dict = {}

    @abstractmethod
    def validate_arguments(self) -> None:
        """Validate all arguments before starting the workflow."""
        pass

    @abstractmethod
    def setup_runtime_environment(self) -> None:
        """Set up the runtime environment (emulator, APK, backend services)."""
        pass

    def setup_agent(self) -> None:
        """Configure and initialize the agent."""
        from agent.custom_agent import CustomAgent

        if self.config.dry_run:
            logger.info("Dry run - skipping agent setup")
            return

        logger.info(f"Setting up agent with {self.config.workflow} prompt...")

        self.agent = CustomAgent(
            model=self.config.model,
            max_iterations=self.config.max_iterations,
            max_model_response_tokens=self.config.max_model_response_tokens,
            screenshot_enabled=self.config.screenshot_mode,
            app_name=self.app_name,
            app_server=self.metadata.get("app_server"),
            package_name=self.metadata.get("package_name"),
            username=self.metadata.get("username"),
            password=self.metadata.get("password"),
            include_ssrf=bool(self.metadata.get("container_names")),
            workflow=self.config.workflow,
            reasoning_effort=self.config.reasoning_effort,
        )
        logger.info(f"Agent configured for {self.config.workflow} mode")

    def run_agent(self) -> dict:
        """Execute the agent and return results."""
        if self.config.dry_run:
            logger.info("Dry run - skipping agent execution")
            return {"status": "dry_run", "turns": 0}

        if not self.agent:
            raise RuntimeError("Agent not initialized. Call setup_agent() first.")

        logger.info(f"Running agent for {self.config.workflow}...")
        self.agent_result = self.agent.run()
        logger.info(f"Agent completed with status: {self.agent_result.get('status')}")
        return self.agent_result

    @abstractmethod
    def evaluate(self) -> dict:
        """Evaluate the results and return scores."""
        pass

    def save_artifacts(self, logs_dir: Path) -> None:
        """Save agent artifacts (exploit files, agent output) to logs.

        Best-effort: logs warnings on failure but never raises.
        Called after run_agent() while the container is still alive.
        """
        if not self.agent_env:
            return

        for save_fn in (
            self.agent_env.save_agent_exploit,
            self.agent_env.save_agent_output,
        ):
            try:
                save_fn(logs_dir)
            except Exception as e:
                logger.warning(f"Failed to save artifacts: {e}")

    def cleanup(self) -> None:
        """Clean up resources (emulator, containers, etc.)."""
        if self.emulator:
            logger.info("Stopping emulator...")
            self.emulator.stop()
        if self.agent_env:
            logger.info("Cleaning up agent environment...")
            self.agent_env.cleanup()
