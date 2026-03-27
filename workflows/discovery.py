"""DiscoveryWorkflow - for discovering unknown vulnerabilities in applications."""

from pathlib import Path

from utils.logger import logger, logger_manager
from utils.setup_utils import check_connectivity
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
        from utils.command_executor import CommandExecutor
        from utils.emulator_manager import EmulatorManager
        from utils.setup_utils import install_app_and_setup_backend
        from utils.uuid_flags_utils import generate_and_save_flags

        # Determine which generic probes are enabled for this app
        enabled_probes = set(
            self.metadata.get(
                "generic_probes",
                ["access", "availability", "confidentiality", "integrity"],
            )
        )
        logger.info(f"Enabled generic probes: {enabled_probes}")

        needs_flags = bool(enabled_probes & {"confidentiality", "integrity"})

        # Generate fresh flags for this run (only if probes need them)
        container_names = self.metadata.get("container_names", [])
        if needs_flags:
            logger.info(f"Generating flags for containers: {container_names}")
            generate_and_save_flags(str(self.project_root), container_names)
        else:
            logger.info("Skipping flag generation (no probes need it)")

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
        self.setup_apks()

        # Repackage with honeypot activity (only if access probe is enabled)
        if "access" in enabled_probes:
            CommandExecutor().run_with_progress(
                f"bash ../../utils/repackage_apk.sh apk/{self.app_name}.apk",
                timeout=self.config.build_command_timeout,
                message="Repackaging APK",
                cwd=self.app_dir,
            )
        else:
            logger.info("Skipping honeypot repackaging (access probe disabled)")

        # Explicit boot gate — emulator must be ready before CA injection
        self.emulator.wait_until_ready(
            timeout=self.config.emulator_boot_timeout_seconds
        )

        # Inject system CA so apps trust local HTTPS backends (skip for apps
        # with no backend server — they don't need it and injection is flaky).
        if self.metadata.get("app_server"):
            from utils.emulator_certs import inject_system_ca

            inject_system_ca(self.project_root)
        else:
            logger.info("No app_server configured — skipping CA injection")

        # Set up socat port forwards for container emulator mode
        self.emulator.setup_port_forwards(self.app_dir)

        # Install app and setup backend (with SSRF listener for discovery mode)
        install_app_and_setup_backend(
            self.app_dir,
            self.emulator,
            self.project_root,
            start_ssrf="access" in enabled_probes,
            inject_flags=needs_flags,
            build_command_timeout=self.config.build_command_timeout,
        )

        # Setup agent container
        self.agent_env = setup_agent_environment(
            app_dir=self.app_dir,
            agent_image=self.config.agent_image,
            metadata=self.metadata,
            workflow="discovery",
            agent_mode=self.config.agent_mode,
        )

        check_connectivity(self.agent_env.container, self.metadata.get("app_server"))

    def _build_apks_from_source(self) -> None:
        from utils.command_executor import CommandExecutor

        CommandExecutor().run_with_progress(
            f"bash ./build_apk.sh {self.app_name}",
            timeout=self.config.build_command_timeout,
            message="Building clean APK",
            cwd=self.project_root,
        )

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
                timeout=self.config.script_timeout,
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
