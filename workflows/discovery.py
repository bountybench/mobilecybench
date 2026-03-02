"""DiscoveryWorkflow - for discovering unknown vulnerabilities in applications."""

from pathlib import Path

from models.config import (
    DEFAULT_BUILD_COMMAND_TIMEOUT,
    DEFAULT_EMULATOR_BOOT_TIMEOUT_SECONDS,
    DEFAULT_SCRIPT_TIMEOUT,
)
from utils.logger import logger, logger_manager
from utils.setup_utils import check_connectivity
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
        script_timeout: int = DEFAULT_SCRIPT_TIMEOUT,
        build_command_timeout: int = DEFAULT_BUILD_COMMAND_TIMEOUT,
        emulator_boot_timeout_seconds: int = DEFAULT_EMULATOR_BOOT_TIMEOUT_SECONDS,
        screenshot_mode: bool = False,
        build_type: str = "source",
        agent_image: str = "cybench/mobilecybench:latest",
        project_root: Optional[Path] = None,
        dry_run: bool = False,
        reasoning_effort: Optional[str] = None,
        docker_mode: bool = False,
        emulator_mode: str = "native",
    ):
        self.app_name = app_name
        self.app_dir = app_dir
        self.model = model
        self.max_iterations = max_iterations
        self.max_model_response_tokens = max_model_response_tokens
        self.script_timeout = script_timeout
        self.build_command_timeout = build_command_timeout
        self.emulator_boot_timeout_seconds = emulator_boot_timeout_seconds
        self.screenshot_mode = screenshot_mode
        self.build_type = build_type
        self.agent_image = agent_image
        self.project_root = project_root or Path(__file__).parent.parent
        self.dry_run = dry_run
        self.reasoning_effort = reasoning_effort
        self.docker_mode = docker_mode
        self.emulator_mode = emulator_mode

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

        if not (self.app_dir / "metadata.json").exists():
            raise ValueError(f"metadata.json not found in {self.app_dir}")

        # Load metadata for later use
        from utils.utils import get_app_metadata

        self.metadata = get_app_metadata(self.app_name)

    def setup_runtime_environment(self) -> None:
        """Set up emulator, APK, backend containers, and agent environment."""
        from agent.agent_container import setup_agent_environment
        from utils.apk_utils import setup_apk
        from utils.emulator_manager import EmulatorManager
        from utils.setup_utils import install_app_and_setup_backend
        from utils.uuid_flags_utils import generate_and_save_flags

        # Generate fresh flags for this run (discovery mode only)
        container_names = self.metadata.get("container_names", [])
        logger.info(f"Generating flags for containers: {container_names}")
        generate_and_save_flags(str(self.project_root), container_names)

        logger.info("Starting emulator...")
        self.emulator = EmulatorManager(
            project_root=self.project_root,
            sdk_version=self.metadata.get("sdk"),
            app_name=self.app_name,
            rootable=True,
            emulator_backend=self.config.emulator_backend,
            emulator_display=self.config.emulator_display,
        )
        self.emulator.start_in_background()
        logger.info("Emulator started in background")

        # Build/download APK (can run while emulator boots)
        setup_apk(self.app_dir, self.config.build_type, self.project_root)

        # Explicit boot gate — emulator must be ready before CA injection
        self.emulator.wait_until_ready(timeout=self.emulator_boot_timeout_seconds)

        # Inject system CA so apps trust local HTTPS backends
        from utils.emulator_certs import inject_system_ca

        inject_system_ca(self.project_root)

        # Install app and setup backend (with SSRF listener for discovery mode)
        install_app_and_setup_backend(
            self.app_dir,
            self.emulator,
            self.project_root,
            start_ssrf=True,
            build_command_timeout=self.build_command_timeout,
        )

        # Setup agent container
        self.agent_env = setup_agent_environment(
            app_dir=self.app_dir,
            agent_image=self.config.agent_image,
            metadata=self.metadata,
            workflow="discovery",
        )

        check_connectivity(self.agent_env.container, self.metadata.get("app_server"))

    def evaluate(self) -> dict:
        """Evaluate using probe-based checks."""
        import json
        import os
        import shlex

        from utils.command_executor import CommandExecutor

        if self.config.dry_run:
            logger.info("Dry run - skipping evaluation")
            return {"scores": {}}

        logger.info("Running probe-based evaluation...")
        cmd = CommandExecutor()

        log_path = Path(logger_manager.get_agent_log_file_name())

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
            result = cmd.run(
                command,
                cwd=self.project_root,
                check=False,
                env=env,
                timeout=self.script_timeout,
            )
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
