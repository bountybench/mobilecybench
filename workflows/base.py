"""Base workflow class defining the evaluation interface."""

import logging
import shutil
import subprocess
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
        if self.config.dry_run:
            logger.info("Dry run - skipping agent setup")
            return

        agent_mode = self.config.agent_mode
        workflow = self.config.workflow
        include_ssrf = bool(self.metadata.get("container_names"))

        logger.info(f"Setting up agent (mode={agent_mode}) with {workflow} prompt...")

        if agent_mode == "claude-code":
            from agent.claude_code_agent import ClaudeCodeAgent

            self.agent = ClaudeCodeAgent(
                app_name=self.app_name,
                model=self.config.model,
                timeout_ms=self.config.agent_timeout * 1000,
                app_server=self.metadata.get("app_server"),
                package_name=self.metadata.get("package_name"),
                username=self.metadata.get("username"),
                password=self.metadata.get("password"),
                include_ssrf=include_ssrf,
                workflow=workflow,
            )
        elif agent_mode == "codex":
            from agent.codex_agent import CodexAgent

            self.agent = CodexAgent(
                app_name=self.app_name,
                app_server=self.metadata.get("app_server"),
                package_name=self.metadata.get("package_name"),
                username=self.metadata.get("username"),
                password=self.metadata.get("password"),
                include_ssrf=include_ssrf,
            )
        else:
            from agent.custom_agent import CustomAgent

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
                include_ssrf=include_ssrf,
                workflow=workflow,
                reasoning_effort=self.config.reasoning_effort,
            )
        logger.info(f"Agent configured for {workflow} mode (mode={agent_mode})")

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

    def setup_apks(self) -> None:
        """Acquire APKs based on build_type.

        Handles skip-apk and download-apk centrally.
        For source builds, delegates to subclass ``_build_apks_from_source()``.
        """
        if self.config.build_type == "skip-apk":
            logger.info("skip-apk: assuming APKs already present")
            return

        if self.config.build_type == "download-apk":
            from utils.apk_utils import download_apk, get_download_url

            url = get_download_url(self.app_name, self.project_root)
            if not url:
                raise FileNotFoundError(
                    f"No download_link in apps/{self.app_name}/metadata.json. "
                    f"Build and publish: ./publish_apk_bundle.sh apps/{self.app_name}"
                )
            download_apk(self.app_name, url, self.project_root)
            return

        self._build_apks_from_source()

    def _build_apks_from_source(self) -> None:
        """Build APKs from source. Subclasses must override."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement _build_apks_from_source()"
        )

    # -- Shared replay helpers (used by exploit & detection workflows) --------

    def _restart_runtime(self, apk_path: Path, prepare_app_hook: Path = None) -> None:
        """Restart emulator and app servers with the given APK.

        Args:
            apk_path: Relative path to the APK within app_dir.
            prepare_app_hook: Optional shell script to run after install.
        """
        from utils.command_executor import CommandExecutor
        from utils.emulator_certs import inject_system_ca
        from utils.setup_utils import install_app_and_setup_backend

        logger.info(f"Restarting runtime with APK: {apk_path}")
        self.emulator.restart()
        self.emulator.wait_until_ready(
            timeout=self.config.emulator_boot_timeout_seconds
        )
        inject_system_ca(self.project_root)
        install_app_and_setup_backend(
            self.app_dir,
            self.emulator,
            self.project_root,
            apk_path=apk_path,
            inject_flags=False,
            build_command_timeout=self.config.build_command_timeout,
        )

        if prepare_app_hook and prepare_app_hook.exists():
            logger.info(f"Running prepare_app hook: {prepare_app_hook}")
            cmd = CommandExecutor()
            cmd.run_with_progress(
                f"bash {prepare_app_hook}",
                timeout=self.config.script_timeout,
                message="Running prepare_app hook",
                cwd=self.app_dir,
            )

        logger.info("Runtime restarted successfully")

    def _run_exploit(
        self,
        exploit_dir: Path,
        output_dir: Path,
        exploit_runner: Path,
        exploit_image: str,
        app_server: str = None,
        *,
        codebase_dir: Path,
    ) -> dict:
        """Replay exploit.sh via run_exploit_container.sh.

        Connectivity (ADB + app server) is checked by the script itself.
        """
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        replay_cmd = [
            "bash",
            str(exploit_runner),
            "--exploit-dir",
            str(exploit_dir),
            "--output-dir",
            str(output_dir),
            "--image",
            exploit_image,
            "--utils-dir",
            str(self.project_root / "utils"),
        ]
        if app_server:
            replay_cmd += ["--app-server", app_server]
        replay_cmd += ["--codebase-dir", str(codebase_dir)]
        proc = subprocess.run(
            replay_cmd,
            cwd=self.project_root,
            capture_output=True,
            text=True,
        )
        stdout = proc.stdout.strip()
        stderr = proc.stderr.strip()

        logger.info(f"Exploit replay exit_code={proc.returncode}")
        if stdout:
            logger.info(f"Exploit replay stdout:\n{stdout}")
        if stderr:
            logger.info(f"Exploit replay stderr:\n{stderr}")

        return {
            "replay_exit_code": proc.returncode,
            "replay_stdout": stdout,
            "replay_stderr": stderr,
            "image": exploit_image,
        }

    def cleanup(self) -> None:
        """Clean up resources (emulator, agent env) and restore codebase."""
        if self.emulator:
            logger.info("Stopping emulator...")
            self.emulator.stop()
        if self.agent_env:
            logger.info("Cleaning up agent environment...")
            self.agent_env.cleanup()

        # Restore codebase to clean state — workflows may apply patches during
        # setup or evaluate. This is a no-op if codebase is already clean.
        codebase_dir = self.app_dir / "codebase"
        if codebase_dir.exists():
            try:
                from utils.git_utils import git_restore_clean

                git_restore_clean(codebase_dir)
            except Exception as e:
                logger.warning(f"Failed to restore codebase: {e}")

        # Delete agent_codebase — created during setup, needed through evaluate(),
        # but should not persist between runs.
        agent_codebase = self.app_dir / "agent_codebase"
        if agent_codebase.exists():
            try:
                shutil.rmtree(agent_codebase)
                logger.info("Deleted agent_codebase")
            except Exception as e:
                logger.warning(f"Failed to delete agent_codebase: {e}")
