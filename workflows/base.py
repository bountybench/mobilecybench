"""Base workflow class defining the evaluation interface."""

import logging
from abc import ABC, abstractmethod
from pathlib import Path

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

    # Set by subclasses during setup_runtime_environment()
    agent_env = None

    @abstractmethod
    def validate_arguments(self) -> None:
        """Validate all arguments before starting the workflow."""
        pass

    @abstractmethod
    def setup_runtime_environment(self) -> None:
        """Set up the runtime environment (emulator, APK, backend services)."""
        pass

    @abstractmethod
    def setup_agent(self) -> None:
        """Configure and initialize the agent."""
        pass

    @abstractmethod
    def run_agent(self) -> dict:
        """Execute the agent and return results."""
        pass

    @abstractmethod
    def evaluate(self) -> dict:
        """Evaluate the results and return scores."""
        pass

    def save_artifacts(self, logs_dir: Path) -> None:
        """Save agent artifacts (exploit files, codebase diff) to logs.

        Best-effort: logs warnings on failure but never raises.
        Called after run_agent() while the container is still alive.
        """
        if not self.agent_env:
            return

        try:
            self.agent_env.save_exploit_files(logs_dir)
        except Exception as e:
            logger.warning(f"Failed to save exploit_files: {e}")

        try:
            diff = self.agent_env.save_agent_codebase_state()
            if diff:
                diff_path = logs_dir / "agent_codebase.diff"
                diff_path.write_text(diff)
                logger.info(f"Saved agent codebase diff to {diff_path}")
        except Exception as e:
            logger.warning(f"Failed to save agent codebase diff: {e}")

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up resources (emulator, containers, etc.)."""
        pass
