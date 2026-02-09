"""DiscoveryWorkflow - for discovering unknown vulnerabilities in applications."""

from pathlib import Path
from typing import Optional

from utils.logger import logger, logger_manager
from workflows.base import Workflow


class DiscoveryWorkflow(Workflow):
    """
    Workflow for discovering unknown vulnerabilities.

    The agent explores the codebase, identifies vulnerabilities,
    and creates an exploit. Evaluation uses probe-based checks.
    """

    def __init__(
        self,
        app_name: str,
        app_dir: Path,
        model: str,
        max_iterations: int,
        max_model_response_tokens: int,
        max_kali_message_tokens: int,
        max_context_length: int,
        screenshot_mode: bool = False,
        build_type: str = "source",
        agent_image: str = "cybench/mobilecybench:latest",
        project_root: Optional[Path] = None,
        dry_run: bool = False,
        reasoning_effort: Optional[str] = None,
        thinking_budget: Optional[int] = None,
    ):
        self.app_name = app_name
        self.app_dir = app_dir
        self.model = model
        self.max_iterations = max_iterations
        self.max_model_response_tokens = max_model_response_tokens
        self.max_kali_message_tokens = max_kali_message_tokens
        self.max_context_length = max_context_length
        self.screenshot_mode = screenshot_mode
        self.build_type = build_type
        self.agent_image = agent_image
        self.project_root = project_root or Path(__file__).parent.parent
        self.dry_run = dry_run
        self.reasoning_effort = reasoning_effort
        self.thinking_budget = thinking_budget

        # Set during setup
        self.metadata: dict = {}
        self.emulator = None
        self.agent_env = None
        self.agent = None
        self.agent_result: dict = {}

    def validate_arguments(self) -> None:
        """Validate that app directory exists and has required files."""
        if not self.app_dir.exists():
            raise ValueError(f"App directory not found: {self.app_dir}")

        metadata_path = self.app_dir / "metadata.json"
        if not metadata_path.exists():
            raise ValueError(f"metadata.json not found in {self.app_dir}")

        # Load metadata for later use
        from utils.utils import get_app_metadata

        self.metadata = get_app_metadata(self.app_name)

    def setup_runtime_environment(self) -> None:
        """Set up emulator, APK, backend containers, and agent environment."""
        from agent.agent_setup import setup_agent_environment
        from utils.apk_utils import setup_apk
        from utils.emulator_manager import EmulatorManager
        from utils.setup_utils import install_app_and_setup_backend
        from utils.uuid_flags_utils import generate_and_save_flags

        # Generate fresh flags for this run (discovery mode only)
        container_names = self.metadata.get("container_names", [])
        logger.info(f"Generating flags for containers: {container_names}")
        generate_and_save_flags(str(self.project_root), container_names)

        # Start emulator
        logger.info("Starting emulator...")
        sdk_version = self.metadata.get("sdk")
        self.emulator = EmulatorManager(
            docker_mode=False,
            project_root=self.project_root,
            sdk_version=sdk_version,
            app_name=self.app_name,
            rootable=True,
        )
        self.emulator.start_in_background()
        logger.info("Emulator started in background")

        # Build/download APK
        setup_apk(self.app_dir, self.build_type, self.project_root)

        # Install app and setup backend (with SSRF listener for discovery mode)
        install_app_and_setup_backend(
            self.app_dir,
            self.emulator,
            self.project_root,
            start_ssrf=True,
        )

        # Setup agent container
        self.agent_env = setup_agent_environment(
            app_dir=self.app_dir,
            agent_image=self.agent_image,
            metadata=self.metadata,
            workflow="discovery",
        )

    def setup_agent(self) -> None:
        """Configure agent with discovery prompt."""
        from agent.custom_agent import CustomAgent

        if self.dry_run:
            logger.info("Dry run - skipping agent setup")
            return

        logger.info("Setting up agent with discovery prompt...")

        # Determine if SSRF instructions should be included
        container_names = self.metadata.get("container_names", [])
        include_ssrf = bool(container_names)

        self.agent = CustomAgent(
            model=self.model,
            max_iterations=self.max_iterations,
            max_model_response_tokens=self.max_model_response_tokens,
            max_kali_message_tokens=self.max_kali_message_tokens,
            max_context_length=self.max_context_length,
            screenshot_enabled=self.screenshot_mode,
            app_name=self.app_name,
            app_server=self.metadata.get("app_server"),
            package_name=self.metadata.get("package_name"),
            username=self.metadata.get("username"),
            password=self.metadata.get("password"),
            include_ssrf=include_ssrf,
            workflow="discovery",
            reasoning_effort=self.reasoning_effort,
            thinking_budget=self.thinking_budget,
        )
        logger.info("Agent configured for discovery mode")

    def run_agent(self) -> dict:
        """Execute the agent to discover vulnerabilities."""
        if self.dry_run:
            logger.info("Dry run - skipping agent execution")
            return {"status": "dry_run", "turns": 0}

        if not self.agent:
            raise RuntimeError("Agent not initialized. Call setup_agent() first.")

        logger.info("Running agent for vulnerability discovery...")
        self.agent_result = self.agent.run()
        logger.info(f"Agent completed with status: {self.agent_result.get('status')}")
        return self.agent_result

    def evaluate(self) -> dict:
        """Evaluate using probe-based checks."""
        import json
        import os
        import shlex

        from utils.command_executor import CommandExecutor

        if self.dry_run:
            logger.info("Dry run - skipping evaluation")
            return {"scores": {}}

        logger.info("Running probe-based evaluation...")
        cmd = CommandExecutor()

        # Get agent log file path
        log_file_path = logger_manager.get_agent_log_file_name()
        log_path = Path(log_file_path)

        app_relative_path = f"apps/{self.app_name}"
        command = f"bash ./run_checks.sh {shlex.quote(app_relative_path)}"

        if log_path.exists() and log_path.is_file():
            command = f"{command} {shlex.quote(str(log_path))}"

        # Skip SSRF check if no backend containers
        container_names = self.metadata.get("container_names", [])
        env = os.environ.copy()
        if not container_names:
            env["SKIP_SSRF_CHECK"] = "1"

        try:
            result = cmd.run(command, cwd=self.project_root, check=False, env=env)
            if result.stdout:
                logger.info(result.stdout)
            if result.stderr:
                logger.info(result.stderr)
        except Exception as e:
            logger.error(f"Failed to run probe checks: {e}")
            return {"scores": {}, "error": str(e)}

        # Read scores from file
        scores_file = self.app_dir / "scores.json"
        scores = {}
        if scores_file.exists():
            try:
                with open(scores_file, "r") as f:
                    scores = json.load(f)
                logger.info(f"Probe scores: {scores}")
            except Exception as e:
                logger.error(f"Error reading scores.json: {e}")

        return {"scores": scores}

    def cleanup(self) -> None:
        """Clean up resources."""
        if self.emulator:
            logger.info("Stopping emulator...")
            self.emulator.stop()
        if self.agent_env:
            logger.info("Cleaning up agent environment...")
            self.agent_env.cleanup()
