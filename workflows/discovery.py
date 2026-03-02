"""DiscoveryWorkflow - for discovering unknown vulnerabilities in applications."""

from pathlib import Path

from utils.logger import logger, logger_manager
from workflows.base import Workflow


class DiscoveryWorkflow(Workflow):
    """
    Workflow for discovering unknown vulnerabilities.

    The agent explores the codebase, identifies vulnerabilities,
    and creates an exploit. Evaluation uses probe-based checks.
    """

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
            docker_mode=self.config.docker_mode,
            project_root=self.project_root,
            sdk_version=self.metadata.get("sdk"),
            app_name=self.app_name,
            rootable=True,
            emulator_mode=self.config.emulator_mode,
        )
        self.emulator.start_in_background()
        logger.info("Emulator started in background")

        # Build/download APK (can run while emulator boots)
        setup_apk(self.app_dir, self.config.build_type, self.project_root)

        # Explicit boot gate — emulator must be ready before CA injection
        self.emulator.wait_until_ready()

        # Inject system CA so apps trust local HTTPS backends
        from utils.emulator_certs import inject_system_ca

        inject_system_ca(self.project_root)

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
            agent_image=self.config.agent_image,
            metadata=self.metadata,
            workflow="discovery",
        )

        # TODO(robustness): call check_connectivity() here to fail fast on
        # infra issues before running the agent
        # (see utils.setup_utils.check_connectivity)

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

        # TODO(robustness): run_checks.sh has no timeout — a hung probe
        # script blocks the runner indefinitely. Use script_timeout
        # (already accepted by __init__) or run_with_progress.
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
