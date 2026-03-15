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
        include_ssrf = workflow == "discovery" and bool(
            self.metadata.get("container_names")
        )

        additional_context = self.metadata.get("additional_info")

        logger.info(f"Setting up agent (mode={agent_mode}) with {workflow} prompt...")

        if agent_mode == "claude-code":
            from agent.claude_code_agent import ClaudeCodeAgent

            self.agent = ClaudeCodeAgent(
                app_name=self.app_name,
                model=self.config.model,
                timeout_ms=self.config.agent_timeout * 1000,
                app_server=self.metadata.get("app_server"),
                emulator_server=self.metadata.get("emulator_server"),
                package_name=self.metadata.get("package_name"),
                username=self.metadata.get("username"),
                password=self.metadata.get("password"),
                include_ssrf=include_ssrf,
                workflow=workflow,
                additional_context=additional_context,
            )
        elif agent_mode == "codex":
            from agent.codex_agent import CodexAgent

            self.agent = CodexAgent(
                app_name=self.app_name,
                app_server=self.metadata.get("app_server"),
                emulator_server=self.metadata.get("emulator_server"),
                package_name=self.metadata.get("package_name"),
                username=self.metadata.get("username"),
                password=self.metadata.get("password"),
                include_ssrf=include_ssrf,
                workflow=workflow,
                additional_context=additional_context,
            )
        else:
            from agent.custom_agent import CustomAgent

            self.agent = CustomAgent(
                model=self.config.model,
                max_iterations=self.config.max_iterations,
                max_model_response_tokens=self.config.max_model_response_tokens,
                screenshot_enabled=self.config.screenshot_mode,
                app_name=self.app_name,
                additional_context=additional_context,
                app_server=self.metadata.get("app_server"),
                emulator_server=self.metadata.get("emulator_server"),
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

    def _compose_file_exists(self) -> bool:
        """Return whether the app directory has a Docker Compose file."""
        return any(
            (self.app_dir / name).exists()
            for name in (
                "docker-compose.yml",
                "docker-compose.yaml",
                "compose.yml",
                "compose.yaml",
            )
        )

    def _backend_runtime_state_file(self) -> Path:
        """Path to the marker file recording the last active app backend."""
        runtime_state_dir = self.project_root / ".runtime_state"
        runtime_state_dir.mkdir(parents=True, exist_ok=True)
        return runtime_state_dir / "active_backend_app"

    def _mark_app_backend_active(self) -> None:
        """Record this app as the backend most likely to require cleanup."""
        self._backend_runtime_state_file().write_text(f"{self.app_name}\n")

    def _clear_app_backend_active_marker(self) -> None:
        """Remove the active backend marker if it points to this app."""
        state_file = self._backend_runtime_state_file()
        if not state_file.exists():
            return

        if state_file.read_text().strip() == self.app_name:
            state_file.unlink()

    def _get_stale_backend_app_dir(self) -> Path | None:
        """Return the previously active app directory, if different from this app."""
        state_file = self._backend_runtime_state_file()
        if not state_file.exists():
            return None

        stale_app_name = state_file.read_text().strip()
        if not stale_app_name or stale_app_name == self.app_name:
            return None

        stale_app_dir = self.project_root / "apps" / stale_app_name
        if not stale_app_dir.exists():
            logger.warning(
                "Active backend marker points to missing app directory: %s",
                stale_app_name,
            )
            state_file.unlink(missing_ok=True)
            return None
        return stale_app_dir

    def _run_app_cleanup_script(self, *, check: bool) -> None:
        """Run the app's cleanup.sh script when present."""
        cleanup_script = self.app_dir / "cleanup.sh"
        if not cleanup_script.exists():
            logger.info("No cleanup.sh found for app backend cleanup")
            return

        logger.info(f"Running app cleanup script: {cleanup_script}")
        try:
            subprocess.run(
                ["bash", str(cleanup_script)],
                cwd=self.app_dir,
                timeout=60,
                capture_output=True,
                text=True,
                check=check,
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"App cleanup script failed with exit code {e.returncode}")
            if e.stdout:
                logger.error(f"cleanup.sh stdout:\n{e.stdout.strip()}")
            if e.stderr:
                logger.error(f"cleanup.sh stderr:\n{e.stderr.strip()}")
            raise

    def _run_cleanup_script_for_app_dir(self, app_dir: Path, *, check: bool) -> None:
        """Run cleanup.sh for the given app directory when present."""
        cleanup_script = app_dir / "cleanup.sh"
        if not cleanup_script.exists():
            logger.info(f"No cleanup.sh found for app backend cleanup in {app_dir}")
            return

        logger.info(f"Running app cleanup script: {cleanup_script}")
        try:
            subprocess.run(
                ["bash", str(cleanup_script)],
                cwd=app_dir,
                timeout=60,
                capture_output=True,
                text=True,
                check=check,
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"App cleanup script failed with exit code {e.returncode}")
            if e.stdout:
                logger.error(f"cleanup.sh stdout:\n{e.stdout.strip()}")
            if e.stderr:
                logger.error(f"cleanup.sh stderr:\n{e.stderr.strip()}")
            raise

    def _preflight_cleanup_app_runtime(self) -> None:
        """Best-effort clean slate for stale containers before setup."""
        stale_app_dir = self._get_stale_backend_app_dir()
        if stale_app_dir is not None:
            logger.info(f"Cleaning up stale backend from previous app: {stale_app_dir.name}")
            self._run_cleanup_script_for_app_dir(stale_app_dir, check=True)
        self._run_app_cleanup_script(check=True)

    def _reset_app_backend_state(self) -> None:
        """Drop app backend containers and volumes before replaying evaluation."""
        if not self._compose_file_exists():
            logger.info("No Docker Compose file found - skipping backend volume reset")
            return

        logger.info("Resetting app backend containers and volumes")
        result = subprocess.run(
            ["docker", "compose", "down", "-v"],
            cwd=self.app_dir,
            timeout=60,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout:
            logger.info(f"docker compose down -v stdout:\n{result.stdout.strip()}")
        if result.stderr:
            logger.warning(f"docker compose down -v stderr:\n{result.stderr.strip()}")
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to reset backend containers in {self.app_dir}: "
                f"docker compose down -v exited {result.returncode}"
            )

    # -- Shared replay helpers (used by exploit & detection workflows) --------

    def _restart_runtime(
        self,
        apk_path: Path,
        prepare_app_hook: Path = None,
        *,
        inject_flags: bool = False,
        start_ssrf: bool = False,
    ) -> None:
        """Restart emulator and app servers with the given APK.

        Args:
            apk_path: Relative path to the APK within app_dir.
            prepare_app_hook: Optional shell script to run after install.
            inject_flags: Whether to inject hidden flags for probe evaluation.
            start_ssrf: Whether to start the SSRF listener.
        """
        from utils.command_executor import CommandExecutor
        from utils.emulator_certs import inject_system_ca
        from utils.setup_utils import install_app_and_setup_backend

        logger.info(f"Restarting runtime with APK: {apk_path}")

        # Tear down backend containers so they start with clean state.
        # Without this, Docker containers persist across emulator restarts
        # and retain any state changes the agent made (modified items,
        # created users, changed configs, etc.).
        compose_file = self.app_dir / "docker-compose.yml"
        if compose_file.exists():
            import subprocess as _sp

            logger.info("Tearing down backend containers for clean replay...")
            _sp.run(
                ["docker", "compose", "down", "--volumes", "--remove-orphans"],
                cwd=self.app_dir,
                capture_output=True,
                timeout=60,
            )

        self.emulator.restart()
        self.emulator.wait_until_ready(
            timeout=self.config.emulator_boot_timeout_seconds
        )
        inject_system_ca(self.project_root)
        self.emulator.setup_port_forwards(self.app_dir)
        self._reset_app_backend_state()
        self._mark_app_backend_active()
        install_app_and_setup_backend(
            self.app_dir,
            self.emulator,
            self.project_root,
            apk_path=apk_path,
            inject_flags=inject_flags,
            start_ssrf=start_ssrf,
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
        proc = subprocess.Popen(
            replay_cmd,
            cwd=self.project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        lines = []
        for line in proc.stdout:
            line = line.rstrip("\n")
            lines.append(line)
            logger.info(f"[replay] {line}")
        proc.wait()
        stdout = "\n".join(lines)

        logger.info(f"Exploit replay exit_code={proc.returncode}")

        # Persist replay evidence files
        stdout_path = output_dir / "stdout.txt"
        evidence_path = output_dir / "replay_evidence.log"

        stdout_path.write_text(stdout, encoding="utf-8")

        # Build evidence log: stdout + decodable text from agent_output
        evidence_parts = []
        if stdout:
            evidence_parts.append(f"=== stdout ===\n{stdout}")
        agent_output = output_dir / "agent_output"
        if agent_output.is_dir():
            for fpath in sorted(agent_output.rglob("*")):
                if fpath.is_file():
                    try:
                        text = fpath.read_text(encoding="utf-8", errors="strict")
                        evidence_parts.append(
                            f"=== {fpath.relative_to(output_dir)} ===\n{text}"
                        )
                    except (UnicodeDecodeError, OSError):
                        pass
        evidence_path.write_text("\n".join(evidence_parts), encoding="utf-8")

        return {
            "replay_exit_code": proc.returncode,
            "replay_stdout": stdout,
            "replay_stderr": "",
            "replay_evidence_path": str(evidence_path),
            "image": exploit_image,
        }

    def cleanup(self) -> None:
        """Clean up resources (emulator, agent env, app backends) and restore codebase."""
        try:
            self._run_app_cleanup_script(check=False)
        except Exception as e:
            logger.warning(f"App backend cleanup failed: {e}")
        finally:
            self._clear_app_backend_active_marker()
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
