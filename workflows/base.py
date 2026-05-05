"""Base workflow class defining the evaluation interface."""

import json
import logging
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from models.config import RunnerConfig
from utils.json_io import write_json_atomic

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

    def validate_arguments(self) -> None:
        """Validate common preconditions and load metadata.

        Subclasses override to add workflow-specific checks, calling super() first.
        """
        if not self.app_dir.exists():
            raise ValueError(f"App directory not found: {self.app_dir}")

        metadata_path = self.app_dir / "metadata.json"
        if not metadata_path.exists():
            raise ValueError(f"metadata.json not found in {self.app_dir}")

        with open(metadata_path, encoding="utf-8") as f:
            self.metadata = json.load(f)

    def _agent_credentials(self) -> tuple[str | None, str | None]:
        """Return credentials to expose to the agent prompt.

        App metadata `username`/`password` describe the app or victim setup
        account. Remote-attacker redteam runs may define a separate low-privilege
        attacker account so the prompt does not hand out victim/admin
        credentials as "your credentials".
        """
        if (
            self.config.workflow == "redteam"
            and self.config.attacker_model == "remote_attacker"
        ):
            remote_username = self.metadata.get("remote_attacker_username")
            remote_password = self.metadata.get("remote_attacker_password")
            if remote_username and remote_password:
                return remote_username, remote_password
        return self.metadata.get("username"), self.metadata.get("password")

    @abstractmethod
    def setup_runtime_environment(self) -> None:
        """Set up the runtime environment (emulator, APK, backend services)."""
        pass

    def _resolve_additional_context(self) -> Optional[str]:
        """Build the agent's `additional_context` from metadata + runner config.

        Order is load-bearing: the per-app `metadata.additional_info` carries
        threat-model framing that should appear first; the per-run
        `runner_config.custom_system_prompt` is a runtime knob (hints,
        framing tweaks) appended after it.
        """
        additional_info = self.metadata.get("additional_info")
        extra = self.config.custom_system_prompt
        if not extra:
            return additional_info
        if not additional_info:
            return extra
        return f"{additional_info}\n\n{extra}"

    def setup_agent(self) -> None:
        """Configure and initialize the agent."""
        if self.config.dry_run:
            logger.info("Dry run - skipping agent setup")
            return

        agent_mode = self.config.agent_mode
        workflow = self.config.workflow
        include_ssrf = False

        additional_context = self._resolve_additional_context()
        agent_username, agent_password = self._agent_credentials()

        logger.info(f"Setting up agent (mode={agent_mode}) with {workflow} prompt...")

        # TODO: `config.allowed_tools` is currently honored only by the
        # custom agent. Codex and Claude Code agents drive their own CLI
        # tool surfaces (Codex's native `shell`, Claude Code's built-in
        # tools) and would need a separate filter pass — wire when needed.
        if agent_mode == "claude-code":
            from agent.claude_code_agent import ClaudeCodeAgent

            self.agent = ClaudeCodeAgent(
                app_name=self.app_name,
                model=self.config.model,
                timeout_ms=self.config.agent_timeout * 1000,
                app_server=self.metadata.get("app_server"),
                emulator_server=self.metadata.get("emulator_server"),
                package_name=self.metadata.get("package_name"),
                username=agent_username,
                password=agent_password,
                include_ssrf=include_ssrf,
                workflow=workflow,
                attacker_model=self.config.attacker_model,
                additional_context=additional_context,
                no_codebase=self.config.no_codebase,
                vuln_id=self.config.synthetic_vuln_id or "vuln_0",
            )
        elif agent_mode == "codex":
            from agent.codex_agent import CodexAgent

            self.agent = CodexAgent(
                app_name=self.app_name,
                timeout_ms=self.config.agent_timeout * 1000,
                app_server=self.metadata.get("app_server"),
                emulator_server=self.metadata.get("emulator_server"),
                package_name=self.metadata.get("package_name"),
                username=agent_username,
                password=agent_password,
                include_ssrf=include_ssrf,
                workflow=workflow,
                attacker_model=self.config.attacker_model,
                additional_context=additional_context,
                no_codebase=self.config.no_codebase,
                model=self.config.model,
                reasoning_effort=self.config.reasoning_effort,
                vuln_id=self.config.synthetic_vuln_id or "vuln_0",
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
                timeout_ms=self.config.timeout_ms,
                app_server=self.metadata.get("app_server"),
                emulator_server=self.metadata.get("emulator_server"),
                package_name=self.metadata.get("package_name"),
                username=agent_username,
                password=agent_password,
                include_ssrf=include_ssrf,
                workflow=workflow,
                attacker_model=self.config.attacker_model,
                reasoning_effort=self.config.reasoning_effort,
                no_codebase=self.config.no_codebase,
                allow_unregistered_models=self.config.allow_unregistered_models,
                vuln_id=self.config.synthetic_vuln_id or "vuln_0",
                allowed_tools=self.config.allowed_tools,
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

    def _run_cleanup_script(self, app_dir: Path | None = None, *, check: bool) -> bool:
        """Run cleanup.sh for the given (or current) app directory. Returns success."""
        app_dir = app_dir or self.app_dir
        cleanup_script = app_dir / "cleanup.sh"
        if not cleanup_script.exists():
            logger.info(f"No cleanup.sh found in {app_dir}")
            return True

        logger.info(f"Running cleanup script: {cleanup_script}")
        try:
            result = subprocess.run(
                ["bash", str(cleanup_script)],
                cwd=app_dir,
                timeout=60,
                capture_output=True,
                text=True,
                check=check,
            )
            if result.returncode != 0:
                logger.warning(
                    "cleanup.sh exited non-zero (exit code %s)", result.returncode
                )
                if result.stdout:
                    logger.warning(f"cleanup.sh stdout:\n{result.stdout.strip()}")
                if result.stderr:
                    logger.warning(f"cleanup.sh stderr:\n{result.stderr.strip()}")
                return False
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"cleanup.sh failed with exit code {e.returncode}")
            if e.stdout:
                logger.error(f"cleanup.sh stdout:\n{e.stdout.strip()}")
            if e.stderr:
                logger.error(f"cleanup.sh stderr:\n{e.stderr.strip()}")
            raise

    def _ensure_shared_docker_network(self) -> None:
        """Ensure ``shared_net`` exists before any app's docker-compose runs."""
        # Lazy import to keep workflow construction free of docker side-effects.
        from agent.agent_container import create_docker_network

        create_docker_network("shared_net")

    def _preflight_cleanup_app_runtime(self) -> None:
        """Best-effort clean slate for stale containers before setup."""
        # Network must exist before any cleanup.sh / start_runtime.sh runs
        # `docker compose up`, otherwise compose aborts on the external
        # network reference.
        self._ensure_shared_docker_network()
        stale_app_dir = self._get_stale_backend_app_dir()
        if stale_app_dir is not None:
            logger.info(
                f"Cleaning up stale backend from previous app: {stale_app_dir.name}"
            )
            self._run_cleanup_script(stale_app_dir, check=True)
        self._run_cleanup_script(check=True)

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

    # -- Shared replay helpers ------------------------------------------------

    def _restart_runtime(
        self,
        apk_path: Path,
        prepare_app_hook: Path | None = None,
        *,
        inject_flags: bool = False,
        start_ssrf: bool = False,
    ) -> None:
        """Restart emulator and app servers with the given APK.

        Args:
            apk_path: Path to the APK to install.
            prepare_app_hook: Optional shell script to run after install.
            inject_flags: Whether to inject hidden flags for probe evaluation.
            start_ssrf: Whether to start the SSRF listener.
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
            container_names=self.metadata.get("container_names", []),
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

    @staticmethod
    def _collect_text_files(
        directory: Path, label_root: Path | None = None
    ) -> list[str]:
        """Collect all decodable text files from a directory as labeled sections."""
        parts = []
        if not directory.is_dir():
            return parts
        root = label_root or directory
        for fpath in sorted(directory.rglob("*")):
            if fpath.is_file():
                try:
                    text = fpath.read_text(encoding="utf-8", errors="strict")
                    parts.append(f"=== {fpath.relative_to(root)} ===\n{text}")
                except (UnicodeDecodeError, OSError):
                    pass
        return parts

    @staticmethod
    def build_evidence_log(
        evidence_path: Path,
        *,
        replay_stdout: str = "",
        agent_output_dir: Path | None = None,
        agent_exploit_dir: Path | None = None,
        agent_log: Path | None = None,
    ) -> None:
        """Assemble evidence log from attacker-controlled sources only.

        Security boundary: evidence_log must contain ONLY attacker-produced
        output. Infrastructure logs (server logs, logcat) must NOT be included
        as they would cause false positives in confidentiality probes (e.g.
        server legitimately logs admin credentials during normal auth).

        Sources (all attacker-controlled):
          - replay_stdout: exploit replay stdout/stderr
          - agent_output_dir: files the agent/exploit wrote (/app/agent_output)
          - agent_exploit_dir: exploit source code the agent produced
          - agent_log: agent conversation log (reasoning, tool calls, extracted data)
        """
        parts = []
        if replay_stdout:
            parts.append(f"=== replay_stdout ===\n{replay_stdout}")
        if agent_output_dir:
            parts.extend(Workflow._collect_text_files(agent_output_dir))
        if agent_exploit_dir:
            parts.extend(Workflow._collect_text_files(agent_exploit_dir))
        if agent_log and agent_log.is_file():
            try:
                text = agent_log.read_text(encoding="utf-8", errors="replace")
                parts.append(f"=== agent.log ===\n{text}")
            except OSError:
                pass
        evidence_path.write_text("\n".join(parts), encoding="utf-8")

    def _run_exploit(
        self,
        exploit_dir: Path,
        output_dir: Path,
        exploit_runner: Path,
        exploit_image: str,
        app_server: str = None,
        *,
        codebase_dir: Path | None,
        replay_apk: Path | None,
        logs_dir: Path | None = None,
    ) -> dict:
        """Replay exploit.sh via run_exploit_container.sh.

        Replay mirrors the agent container's resource model: callers pass
        exactly one of ``codebase_dir`` (no_codebase=False; mounts
        /app/codebase) or ``replay_apk`` (no_codebase=True; the single APK
        file to stage and mount at /app/apk so exploit.sh resolves the same
        path the agent had during the agent phase). The codebase mount is
        the security-load-bearing one — replay must not expose source the
        agent never had. The APK mount is for path-symmetry with the agent
        phase.

        Connectivity (ADB + app server) is checked by the script itself.
        """
        if (codebase_dir is None) == (replay_apk is None):
            raise ValueError("exactly one of codebase_dir or replay_apk must be set")

        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Stage the per-phase APK into a sibling dir of output_dir so it
        # survives the rmtree above, mirroring the agent's single-APK staging
        # at /app/apk (one APK only — never apps/<app>/apk wholesale).
        apk_mount_dir: Path | None = None
        if replay_apk is not None:
            apk_mount_dir = output_dir.parent / f"{output_dir.name}_apk"
            if apk_mount_dir.exists():
                shutil.rmtree(apk_mount_dir)
            apk_mount_dir.mkdir(parents=True)
            shutil.copy2(replay_apk, apk_mount_dir / replay_apk.name)

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
        if codebase_dir is not None:
            replay_cmd += ["--codebase-dir", str(codebase_dir)]
        if apk_mount_dir is not None:
            replay_cmd += ["--apk-dir", str(apk_mount_dir)]
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

        try:
            proc.wait(timeout=self.config.script_timeout)
        except subprocess.TimeoutExpired:
            logger.error(
                f"Exploit replay timed out after {self.config.script_timeout}s, killing process"
            )
            proc.kill()
            proc.wait()

        stdout = "\n".join(lines)

        logger.info(f"Exploit replay exit_code={proc.returncode}")

        stdout_path = output_dir / "stdout.txt"
        evidence_path = output_dir / "replay_evidence.log"
        stdout_path.write_text(stdout, encoding="utf-8")

        self.build_evidence_log(
            evidence_path,
            replay_stdout=stdout,
            agent_output_dir=output_dir / "agent_output",
            agent_exploit_dir=logs_dir / "agent_exploit" if logs_dir else None,
            agent_log=logs_dir / "agent.log" if logs_dir else None,
        )

        return {
            "replay_exit_code": proc.returncode,
            "replay_stdout": stdout,
            "replay_stderr": "",
            "replay_evidence_path": str(evidence_path),
            "image": exploit_image,
        }

    # -- Shared evaluation helpers -----------------------------------------------

    SCORE_FILE = "scores.json"

    def _make_result(self, status: str, score: int = 0, **kwargs) -> dict:
        return {"status": status, "score": score, "scores": {}, **kwargs}

    def _save_and_return(self, status: str, score: int = 0, **kwargs) -> dict:
        """Build result, save, and return. Reduces early-return boilerplate."""
        result = self._make_result(status, score=score, **kwargs)
        self._save_result(result)
        return result

    def _save_result(self, result: dict) -> None:
        scores_file = self.app_dir / self.SCORE_FILE
        write_json_atomic(scores_file, result)
        logger.info(f"Result saved to {scores_file}")

    def _run_checks(
        self,
        exploit_log_path: str,
        *,
        app_scores_out: Path,
        generic_scores_out: Path,
        probe_dir: Path,
    ) -> bool:
        """Run run_checks.sh with explicit output paths. Returns True on success.

        Args:
            probe_dir: Directory containing probe scripts (test_*.py).
        """
        check_dir = probe_dir

        run_checks = check_dir / "run_checks.sh"
        if not run_checks.exists():
            run_checks = self.project_root / "run_checks.sh"

        env = os.environ.copy()
        env["APP_SCORES_OUT"] = str(app_scores_out)
        env["GENERIC_SCORES_OUT"] = str(generic_scores_out)

        if not self.metadata.get("container_names"):
            env["SKIP_SSRF_CHECK"] = "1"

        args = [str(check_dir)]
        if exploit_log_path:
            args.append(exploit_log_path)

        cmd = ["bash", str(run_checks)] + args
        logger.info(f"Running checks: {' '.join(cmd)}")
        proc = subprocess.run(
            cmd,
            cwd=check_dir,
            capture_output=True,
            text=True,
            env=env,
        )

        if proc.returncode != 0:
            logger.error(f"run_checks.sh failed (exit {proc.returncode})")
            if proc.stderr:
                logger.error(f"stderr: {proc.stderr}")
            return False

        for path in (app_scores_out, generic_scores_out):
            if path.exists():
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in {path}")
                    return False
            else:
                logger.warning(f"Score output file not produced: {path}")

        return True

    def _isolate_backend(self) -> None:
        """Disconnect backend containers from shared_net during replay."""
        if not self.metadata.get("isolate_backend_during_replay"):
            return
        for name in self.metadata.get("container_names", []):
            logger.info(f"Isolating backend: disconnecting {name} from shared_net")
            subprocess.run(
                ["docker", "network", "disconnect", "shared_net", name],
                capture_output=True,
            )

    def _restore_backend(self) -> None:
        """Reconnect backend containers to shared_net after replay."""
        if not self.metadata.get("isolate_backend_during_replay"):
            return
        for name in self.metadata.get("container_names", []):
            logger.info(f"Restoring backend: reconnecting {name} to shared_net")
            subprocess.run(
                ["docker", "network", "connect", "shared_net", name],
                capture_output=True,
            )

    def _clear_ssrf_requests(self) -> None:
        """Clear SSRF listener state before a probe replay."""
        try:
            from utils.ssrf_utils import clear_ssrf_requests

            clear_ssrf_requests()
        except ImportError:
            logger.warning("ssrf_utils not available — skipping SSRF clear")

    def cleanup(self) -> None:
        """Clean up resources (emulator, agent env, app backends) and restore codebase."""
        cleanup_ok = True
        try:
            cleanup_ok = self._run_cleanup_script(check=False)
        except Exception as e:
            cleanup_ok = False
            logger.warning(f"App backend cleanup failed: {e}")
        finally:
            if cleanup_ok:
                self._clear_app_backend_active_marker()
            else:
                logger.warning(
                    "Preserving active backend marker because app cleanup did not complete successfully"
                )
        if self.emulator:
            logger.info("Stopping emulator...")
            try:
                self.emulator.stop()
            except RuntimeError as e:
                logger.error(f"Emulator cleanup failed: {e}")
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

        # Delete agent_apk staging directory (created when no_codebase=True)
        agent_apk = self.app_dir / "agent_apk"
        if agent_apk.exists():
            try:
                shutil.rmtree(agent_apk)
                logger.info("Deleted agent_apk")
            except Exception as e:
                logger.warning(f"Failed to delete agent_apk: {e}")
