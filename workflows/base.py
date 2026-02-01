"""Base workflow class defining the evaluation interface."""

from abc import ABC, abstractmethod


class Workflow(ABC):
    """
    Abstract base class for evaluation workflows.

    Each workflow defines how to:
    1. Validate arguments before starting
    2. Set up the runtime environment (emulator, APK, backend)
    3. Configure and initialize the agent
    4. Run the agent
    5. Evaluate the results
    """

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

    @abstractmethod
    def cleanup(self) -> None:
        """Clean up resources (emulator, containers, etc.)."""
        pass
