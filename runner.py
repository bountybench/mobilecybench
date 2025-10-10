#!/usr/bin/env python3
"""
Mobile Cybench Runner Script

This script orchestrates the complete pipeline for running cybersecurity tests
on Android applications using AI agents.
"""

import argparse
import datetime
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from selectors import EVENT_READ, DefaultSelector
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from utils.logger import logger, logger_manager
from utils.utils import get_app_metadata

load_dotenv()
project_root = Path(__file__).parent


class CommandExecutor:
    def __init__(self):
        pass

    def run(
        self,
        command: str,
        cwd: Optional[Path] = None,
        check: bool = True,
        capture_output: bool = True,
        live_output: bool = False,
        env: Optional[Dict[str, str]] = None,
    ) -> subprocess.CompletedProcess:
        """
        Runs a shell command securely.

        Args:
            command: The command string to execute.
            cwd: The working directory for the command.
            check: If True, raises an exception on non-zero exit codes.
            capture_output: If True, captures stdout and stderr.
            live_output: If True, streams command output to the logger in real-time.
            env: Optional environment variables for the subprocess.

        Returns:
            A CompletedProcess object.
        """
        args = shlex.split(command)
        logger.info(f"Preparing command: `{' '.join(args)}` in `{cwd or '.'}`")

        try:
            if live_output:
                return self._run_with_live_output(args, cwd, check, env)

            result = subprocess.run(
                args,
                cwd=cwd,
                capture_output=capture_output,
                text=True,
                check=False,  # We handle the check manually
                env=env,
            )

            if result.stdout:
                logger.debug(f"STDOUT:\n{result.stdout.strip()}")
            if result.stderr:
                logger.warning(f"STDERR:\n{result.stderr.strip()}")

            if check and result.returncode != 0:
                raise subprocess.CalledProcessError(
                    result.returncode, args, result.stdout, result.stderr
                )

            return result

        except FileNotFoundError:
            logger.error(f"Command not found: {args[0]}")
            raise
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed with exit code {e.returncode}: `{command}`")
            logger.error(f"STDERR: {e.stderr.strip() if e.stderr else 'N/A'}")
            raise
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while running command `{command}`: {e}"
            )
            raise

    def start_background_process(
        self,
        command: str,
        cwd: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> subprocess.Popen:
        """
        Starts a background process without waiting for it to complete.

        Args:
            command: The command string to execute.
            cwd: The working directory for the command.
            env: Optional environment variables for the subprocess.

        Returns:
            A Popen object for the background process.
        """
        args = shlex.split(command)
        logger.info(
            f"Starting background process: `{' '.join(args)}` in `{cwd or '.'}`"
        )

        try:
            process = subprocess.Popen(
                args,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            logger.info(f"Background process started with PID: {process.pid}")
            return process
        except FileNotFoundError:
            logger.error(f"Command not found: {args[0]}")
            raise
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while starting background process `{command}`: {e}"
            )
            raise

    def _run_with_live_output(
        self,
        args: List[str],
        cwd: Optional[Path],
        check: bool,
        env: Optional[Dict[str, str]],
    ) -> subprocess.CompletedProcess:
        """Helper to stream output in real-time."""
        stdout_lines = []
        stderr_lines = []

        process = subprocess.Popen(
            args,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        selector = DefaultSelector()
        selector.register(process.stdout, EVENT_READ)
        selector.register(process.stderr, EVENT_READ)

        while process.poll() is None and selector.get_map():
            events = selector.select(timeout=0.1)
            for key, _ in events:
                line = key.fileobj.readline()
                if not line:
                    selector.unregister(key.fileobj)
                    continue

                if key.fileobj == process.stdout:
                    logger.info(line.strip())
                    stdout_lines.append(line)
                else:
                    logger.warning(line.strip())
                    stderr_lines.append(line)

        stdout, stderr = process.communicate()
        if stdout:
            for line in stdout.splitlines():
                logger.info(line.strip())
                stdout_lines.append(line + "\n")
        if stderr:
            for line in stderr.splitlines():
                logger.warning(line.strip())
                stderr_lines.append(line + "\n")

        if check and process.returncode != 0:
            raise subprocess.CalledProcessError(
                process.returncode, args, "".join(stdout_lines), "".join(stderr_lines)
            )

        return subprocess.CompletedProcess(
            args=args,
            returncode=process.returncode,
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
        )


class MobileCybenchRunner:
    def __init__(self, app_name: str, config: dict):
        self.app_name = app_name
        self.config = config
        self.project_root = project_root
        self.app_dir = self.project_root / "apps" / app_name
        self.agent_dir = self.project_root / "agent"
        self.cmd = CommandExecutor()

        logger.info("=" * 80)
        logger.info("MobileCybench Runner Started")
        logger.info(f"App: {app_name}")
        logger.info("Configuration:")
        logger.info(f"  Server Access: {config['server_access']}")
        logger.info(f"  Build Type: {config['build_type']}")
        logger.info(f"  ADB Access: {config['adb_access']}")
        logger.info(f"  Max Iterations: {config['max_iterations']}")
        logger.info(f"  Max Kali Message Tokens: {config['max_kali_message_tokens']}")
        logger.info(
            f"  Max Model Response Tokens: {config['max_model_response_tokens']}"
        )
        logger.info(f"  Max Context Length: {config['max_context_length']}")
        logger.info(f"  Model: {config['model']}")
        logger.info(f"  Screenshot Mode: {config['screenshot_mode']}")
        logger.info(f"  Headless Mode: {config['headless_mode']}")
        logger.info(f"  Dry Run: {config['dry_run']}")
        logger.info(f"Timestamp: {datetime.datetime.now()}")
        logger.info("=" * 80)

    def _exit_with_error(self, message: str):
        """Log error and exit"""
        logger.error(message)
        logger.error("Runner execution failed. Check log for details.")
        # TODO: a conditional cleanup based on how far we got until failure
        # for example, if we fail after starting containers, we should stop them
        sys.exit(1)

    def validate_input(self):
        """Validate app name and required files"""
        # TODO: Implement API key validation
        logger.info("Validating input...")

        # Check if app directory exists
        if not self.app_dir.exists():
            self._exit_with_error(f"App directory not found: {self.app_dir}")

        # Validate metadata.json using get_app_metadata
        try:
            self.metadata = get_app_metadata(self.app_name)
            logger.info(f"Metadata loaded: {self.metadata}")
        except Exception as e:
            self._exit_with_error(f"Invalid metadata.json: {e}")

        # Check for required scripts
        required_scripts = ["setup.sh", "run_checks.sh"]
        if self.config["build_type"] == "source":
            required_scripts.append("setup_app_source.sh")
        elif self.config["build_type"] == "download-apk":
            required_scripts.append("setup_app_apklink.sh")
        elif self.config["build_type"] == "skip-apk":
            possible_setup_scripts = ["setup_app_source.sh", "setup_app_apklink.sh"]
            # do not allow skip-apk if neither script exists
            if not any(
                (self.app_dir / script).exists() for script in possible_setup_scripts
            ):
                self._exit_with_error(
                    f"At least one setup script required for build_type 'skip-apk' not found: {possible_setup_scripts}"
                )
        else:
            self._exit_with_error(
                f"Unsupported Build Type Detected: {self.config["build_type"]}"
            )

        for script in required_scripts:
            script_path = self.app_dir / script
            if not script_path.exists():
                self._exit_with_error(f"Required script not found: {script_path}")

        # Check for required ngrok.yml config file
        ngrok_config = self.agent_dir / "mcp" / "ngrok.yml"
        if not ngrok_config.exists():
            self._exit_with_error(
                f"Required ngrok.yml config file not found: {ngrok_config}"
            )

        logger.info("Input validation passed")

    def setup_emulator(self):
        """Start and check Android emulator"""
        logger.info("Setting up Android emulator...")
        try:
            self.cmd.run(f"./setup.sh {self.app_name}", cwd=self.project_root)
        except subprocess.CalledProcessError as e:
            self._exit_with_error(f"Failed to setup emulator: {e}")

        # Start emulator (runs in background - continuous output like docker without detached mode)
        logger.info("Starting emulator in background...")
        # Use --yes to auto-confirm starting another emulator if already running
        self.cmd.start_background_process(
            "bash ./start_emulator.sh --yes",
            cwd=self.project_root,
        )
        logger.info(
            "Emulator setup started, waiting for it to be ready while setting up the app..."
        )

    def setup_app(self, codex_mode=False):
        """APK Handling, App Backend Setup, and App Installation

        Args:
            codex_mode: If True, uses lenient error handling for containerized codex mode
        """
        # Build APK based on build type (custom mode only - codex skips this)
        if not codex_mode:
            if self.config["build_type"] == "skip-apk":
                logger.info("=" * 60)
                logger.info("SKIPPING APK HANDLING STEP")
                logger.info("=" * 60)
            elif self.config["build_type"] == "download-apk":
                logger.info("=" * 60)
                logger.info("FETCHING APK USING APKLINK")
                logger.info("=" * 60)
                try:
                    self.cmd.run(
                        "./setup_app_apklink.sh", cwd=self.app_dir, live_output=True
                    )
                except subprocess.CalledProcessError as e:
                    self._exit_with_error(
                        f"Failed to setup app APK with setup_app_apklink.sh: {e}"
                    )
            else:  # source
                logger.info("=" * 60)
                logger.info("BUILDING APK FROM SOURCE")
                logger.info("=" * 60)
                try:
                    self.cmd.run(
                        "./setup_app_source.sh", cwd=self.app_dir, live_output=True
                    )
                except subprocess.CalledProcessError as e:
                    self._exit_with_error(
                        f"Failed to setup app source with setup_app_source.sh: {e}"
                    )

        # Check emulator status
        logger.info("=" * 60)
        logger.info("CHECKING EMULATOR STATUS")
        logger.info("=" * 60)

        # Quick emulator check
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if "device" not in result.stdout:
                msg = "No Android emulator detected on host"
                if codex_mode:
                    logger.warning(msg)
                    logger.warning("ADB commands may return generic responses")
                    return  # Codex continues without emulator
                else:
                    self._exit_with_error(msg)  # Custom requires emulator

            logger.info("✓ Android emulator detected on host")

        except (
            subprocess.TimeoutExpired,
            subprocess.CalledProcessError,
            FileNotFoundError,
        ) as e:
            msg = f"Could not check emulator status: {e}"
            if codex_mode:
                logger.warning(msg)
                return
            else:
                self._exit_with_error(msg)

        # Wait for emulator to fully boot (custom mode only)
        if not codex_mode:
            logger.info("Waiting for emulator to finish booting...")
            try:
                self.cmd.run(
                    'bash -lc "source utils/wait.sh && wait_for_device_boot 300"',
                    cwd=self.project_root,
                    live_output=True,
                )
            except subprocess.CalledProcessError as e:
                self._exit_with_error(f"Failed to wait for emulator boot: {e}")

            logger.info("Emulator booted. Running ./check_device.sh to verify...")
            try:
                self.cmd.run(
                    "./check_device.sh", cwd=self.project_root, live_output=True
                )
            except subprocess.CalledProcessError as e:
                self._exit_with_error(f"Failed to check emulator status: {e}")

        # Setup app backend and install APK
        logger.info("=" * 60)
        logger.info("SETTING UP THE BACKEND AND INSTALLING APK")
        logger.info("=" * 60)

        setup_script = self.app_dir / "setup.sh"
        if not setup_script.exists():
            msg = f"No setup.sh found for app {self.app_name}"
            if codex_mode:
                logger.warning(f"{msg}, skipping app setup")
                return
            else:
                self._exit_with_error(msg)

        try:
            logger.info(f"Running app setup script: {setup_script}")

            if codex_mode:
                # Use subprocess directly with timeout for codex
                result = subprocess.run(
                    ["bash", "./setup.sh"],
                    cwd=self.app_dir,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )

                if result.returncode == 0:
                    logger.info("✓ App setup completed successfully")
                    if result.stdout:
                        for line in result.stdout.splitlines():
                            logger.info(f"[SETUP] {line}")
                else:
                    logger.error(f"App setup failed with exit code {result.returncode}")
                    if result.stderr:
                        for line in result.stderr.splitlines():
                            logger.error(f"[SETUP ERROR] {line}")
            else:
                # Use CommandExecutor with live output for custom
                self.cmd.run("./setup.sh", cwd=self.app_dir, live_output=True)
                logger.info("✓ App setup completed successfully")

        except subprocess.TimeoutExpired:
            msg = "App setup timed out after 5 minutes"
            if codex_mode:
                logger.error(msg)
            else:
                self._exit_with_error(msg)
        except subprocess.CalledProcessError as e:
            msg = f"Failed to setup app: {e}"
            if codex_mode:
                logger.error(msg)
            else:
                self._exit_with_error(msg)
        except Exception as e:
            msg = f"App setup failed: {e}"
            if codex_mode:
                logger.error(msg)
            else:
                self._exit_with_error(msg)

    def setup_agent(self, codex_mode=False):
        """Configure agent environment and start services"""
        logger.info("=" * 60)
        logger.info("SETTING UP AGENT ENVIRONMENT")
        logger.info("=" * 60)
        logger.info("Setting up agent environment...")

        self._setup_env_file()
        self._create_docker_network()
        self._start_containers(codex_mode=codex_mode)
        self._copy_codebase_to_kali()

        logger.info("Agent environment setup completed")
        logger.info("✓ Agent environment setup completed")

    def _setup_env_file(self):
        """Handle .env file creation/update for OpenAI API key"""
        logger.info("Setting up environment file...")

        env_file = self.agent_dir / ".env"
        api_key = None

        # Load existing .env
        if env_file.exists():
            logger.info(f"Loading existing environment from {env_file}")
            load_dotenv(dotenv_path=env_file, override=False)
        else:
            logger.error(
                f"No existing .env file found at {env_file}. Please create one with OPENAI_API_KEY."
            )
            self._exit_with_error("Missing .env file with OPENAI_API_KEY")

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error("OPENAI_API_KEY not found in environment or .env; exiting.")
            self._exit_with_error("OPENAI_API_KEY missing")
        else:
            logger.info("✓ Using OPENAI_API_KEY from environment/.env (no prompt mode)")

        os.environ["OPENAI_API_KEY"] = api_key

    def _create_docker_network(self):
        """Create shared docker network or print already created if it exists"""
        logger.info("Creating docker network 'shared_net'...")

        try:
            # Try to create the network - if it already exists, docker will return an error
            result = self.cmd.run("docker network create shared_net", check=False)

            if result.returncode == 0:
                logger.info("✓ Docker network 'shared_net' created successfully")
            elif "already exists" in result.stderr:
                logger.info("✓ Docker network 'shared_net' already exists")
            else:
                # Some other error occurred
                logger.error(f"Failed to create docker network: {result.stderr}")
                self._exit_with_error("Failed to create docker network 'shared_net'")

        except Exception as e:
            logger.error(f"Failed to create docker network: {e}")
            self._exit_with_error("Failed to create docker network 'shared_net'")

    def _start_containers(self, codex_mode: bool = False):
        """Start the containerized environment.

        Args:
            codex_mode: If True, uses codex-specific configuration.
                    If False, uses custom implementation.
        """
        logger.info("Starting containerized environment...")

        # Build environment variables
        env = os.environ.copy()

        if codex_mode:
            env.update(
                {
                    "APP_NAME": self.app_name,
                    "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
                    "AGENT_TYPE": "codex",
                    "MCP_COMMAND": "python3 mcp_server.py",  # Skip ngrok for codex
                }
            )
            cmd = f"docker compose -f {self.agent_dir / 'docker-compose.yml'} up -d --build"
            cwd = self.project_root
        else:
            start_dir = f"/tmp/{self.app_name}_app"
            env["START_DIR"] = start_dir
            env["AGENT_TYPE"] = "custom"
            logger.info(f"Setting START_DIR environment variable: {start_dir}")
            cmd = "docker compose up -d"
            cwd = self.agent_dir

        # Execute docker compose
        try:
            result = self.cmd.run(cmd, cwd=cwd, env=env)
            logger.info("✓ Containers started successfully")
            if result.stdout:
                logger.debug(f"Docker compose output: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to start containers: {e}")
            if codex_mode:
                raise
            else:
                self._exit_with_error("Failed to start containers")

        # Container verification
        logger.info("Waiting for containers to initialize...")
        time.sleep(5)

        if codex_mode:
            logger.info("Waiting for codex container setup to complete...")
            max_wait = 300  # 5 minutes
            start = time.time()

            while time.time() - start < max_wait:
                result = self.cmd.run(
                    "docker exec kali-container test -f /tmp/codex_setup_complete",
                    check=False,
                )
                if result.returncode == 0:
                    logger.info("✓ Codex setup complete")
                    break
                time.sleep(5)
            else:
                logger.warning("⚠ Codex setup marker not found after 5 minutes")

        logger.info("Checking container status...")
        try:
            result = self.cmd.run("docker ps", cwd=cwd, env=env)
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to check container status: {e}")
            result = None

        if result:
            logger.info(f"Container status:\n{result.stdout}")

            # Verify specific containers are running
            if "mcp-server" in result.stdout and "kali-container" in result.stdout:
                logger.info("✓ Both MCP server and Kali container are running")
            else:
                logger.warning("⚠ Warning: Some containers may not be running properly")

    def _copy_codebase_to_kali(self):
        """Copy app codebase to Kali container"""
        logger.info("Copying app codebase to Kali container...")
        logger.info("Copying app codebase to Kali container...")

        source_path = self.app_dir / "codebase"
        container_name = "kali-container"
        target_path = f"/tmp/{self.app_name}_app"

        if not source_path.exists():
            logger.warning(f"⚠ Warning: Codebase directory not found at {source_path}")
            logger.warning(f"Codebase directory not found: {source_path}")
            return

        logger.info(f"Source: {source_path}")
        logger.info(f"Target: {container_name}:{target_path}")
        logger.info(f"Copying from {source_path} to {container_name}:{target_path}")

        try:
            # Create target directory in container
            try:
                self.cmd.run(f"docker exec {container_name} mkdir -p {target_path}")
            except subprocess.CalledProcessError as e:
                logger.warning(f"Could not create directory in container: {e}")
                logger.warning("⚠ Warning: Could not create directory in container")
                return

            # Copy files to container
            try:
                self.cmd.run(
                    f"docker cp {source_path}/. {container_name}:{target_path}/"
                )
                logger.info(f"✓ Codebase copied successfully to {target_path}")
                logger.info(f"Codebase copied successfully to {target_path}")
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to copy codebase: {e}")
                logger.error("ERROR: Failed to copy codebase to container")

        except Exception as e:
            logger.warning(f"Exception during codebase copy: {e}")
            logger.warning(f"⚠ Warning: Exception during codebase copy: {e}")

    def run_agent(self):
        """Run the custom agent - custom_agent.py"""
        logger.info("=" * 60)
        logger.info("RUNNING CUSTOM AGENT")
        logger.info("=" * 60)
        logger.info("Starting custom agent execution...")

        try:
            # Import the CustomAgent class
            from agent.custom_agent import CustomAgent

            # Create agent instance with dry_run mode for infrastructure testing
            # Set dry_run=False for actual AI execution
            logger.info("Initializing custom agent...")
            logger.info("Creating CustomAgent instance")

            agent = CustomAgent(
                model=self.config["model"],
                max_iterations=self.config["max_iterations"],
                max_model_response_tokens=self.config["max_model_response_tokens"],
                max_kali_message_tokens=self.config["max_kali_message_tokens"],
                max_context_length=self.config["max_context_length"],
                screenshot_enabled=self.config["screenshot_mode"],
                app_name=self.app_name,
                dry_run=self.config["dry_run"],
                app_server=self.metadata.get("app_server", None),
            )

            logger.info("Running agent...")
            logger.info("Executing agent.run()")

            # This can take a while for actual LLM calls
            result = agent.run()

            # Log and display results
            logger.info("Agent execution completed")
            logger.info(f"Agent result: {result}")

            logger.info("=" * 60)
            logger.info("AGENT EXECUTION RESULTS")
            logger.info("=" * 60)
            logger.info(f"Status: {result.get('status', 'Unknown')}")
            logger.info(f"Turns: {result.get('turns', 0)}")
            logger.info(f"Log file: {result.get('log_file', 'None')}")

            if result.get("final_message"):
                logger.info("Final Message:")
                logger.info(f"  {result['final_message']}")

            logger.info("=" * 60)

            return result

        except Exception as e:
            logger.error(f"Error running custom agent: {e}")
            logger.error(f"ERROR: Failed to run custom agent: {e}")
            return {
                "status": f"error: {str(e)}",
                "turns": 0,
                "final_message": None,
                "log_file": None,
            }

    def run_probes_checks(self, log_file_path: Optional[Path] = None):
        logger.info("=" * 60)
        logger.info("RUNNING PROBE CHECKS")
        logger.info("=" * 60)

        command = "./run_checks.sh"
        if log_file_path:
            log_path = Path(log_file_path)
            if log_path.exists():
                relative_log_path = Path("../../") / log_path
                command = f"{command} {shlex.quote(str(relative_log_path))}"
                logger.info(f"Passing log file to probe checks: {relative_log_path}")
            else:
                logger.error(
                    f"Log file path does not exist in repo/ directory: {log_path}, running without it. This may limit the quality of the probes checks."
                )
        try:
            result = self.cmd.run(command, cwd=self.app_dir, check=False)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to run probe checks: {e}")
            result = e

        # Show results (for this script, STDERR contains progress info, not errors)
        if hasattr(result, "stdout") and result.stdout and result.stdout.strip():
            logger.info(result.stdout)
        if hasattr(result, "stderr") and result.stderr and result.stderr.strip():
            logger.info(
                result.stderr
            )  # Don't label as STDERR since it's just progress info

        return_code = getattr(result, "returncode", 1)
        logger.info(f"✓ Probe checks completed (exit code: {return_code})")

        # Check for scores.json file
        scores_file = self.app_dir / "scores.json"
        if scores_file.exists():
            try:
                with open(scores_file, "r") as f:
                    scores_content = f.read()
                logger.info(f"Scores found: {scores_content}")

            except Exception as e:
                logger.error(f"Error reading scores.json: {e}")
                logger.error(f"Error reading scores.json: {e}")
        else:
            logger.info("No scores.json file was created")
            logger.info("No scores.json file found")

        logger.info(f"Probe checks completed with exit code: {return_code}")
        return return_code == 0

    def cleanup(self):
        """Clean up services"""
        # TODO: ./cleanup.sh from apps dir
        # TODO: Stop emulator
        logger.info("Cleaning up services...")

        try:
            # Stop docker compose services
            self.cmd.run("docker compose down", cwd=self.agent_dir, check=False)
            logger.info("Services stopped")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Error during cleanup: {e}")
        except Exception as e:
            logger.warning(f"Error during cleanup: {e}")

    def run(self):
        """Run the complete pipeline"""
        try:
            self.validate_input()
            self.setup_emulator()
            self.setup_app()
            self.run_probes_checks()  # Probes consider it a pass if no log file is provided

            self.setup_agent()
            self.run_agent()

            agent_log_filename = logger_manager.get_log_file_name()
            log_path = Path(agent_log_filename) if agent_log_filename else None
            logger.info(f"Agent log file path: {log_path}")
            self.run_probes_checks(log_file_path=log_path)

            logger.info("=" * 60)
            logger.info("PIPELINE COMPLETED SUCCESSFULLY")
            logger.info("=" * 60)
            logger.info(f"App: {self.app_name}")

            logger.info("Pipeline completed successfully")
            return 0

        except KeyboardInterrupt:
            logger.info("⚠ Runner interrupted by user")
            logger.info("Runner interrupted by user")
            return 1
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            logger.error("Full log available in the log file.")
            logger.error(f"Unexpected error: {e}")
            return 1
        finally:
            pass
            # self.cleanup()


class ContainerizedCodexRunner:
    """Runner for executing Codex agent in isolated containers."""

    def __init__(
        self,
        app_name: str,
        config: dict,
    ):
        """
        Initialize the containerized runner.

        Args:
            app_name: Name of the mobile application to test
            config: Configuration dictionary from load_config()
        """
        self.app_name = app_name
        self.config = config
        self.project_root = project_root  # Uses the global project_root

        # Extract API key from environment
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        if not self.openai_api_key:
            logger.error("OPENAI_API_KEY environment variable is required")
            sys.exit(1)

        # Paths
        self.docker_compose_file = self.project_root / "agent" / "docker-compose.yml"
        self.app_codebase_dir = self.project_root / "apps" / app_name / "codebase"

        # Container names
        self.codex_container_name = "kali-container"
        self.mcp_container_name = "mcp-server"
        self.agent_log_file = None

        # Log configuration
        logger.info("=" * 80)
        logger.info("ContainerizedCodexRunner Configuration")
        logger.info(f"App: {app_name}")
        logger.info(f"Model: {config['model']}")
        logger.info(f"Max Iterations: {config['max_iterations']}")
        logger.info(f"Max Model Response Tokens: {config['max_model_response_tokens']}")
        logger.info(f"Max Kali Message Tokens: {config['max_kali_message_tokens']}")
        logger.info(f"Max Context Length: {config['max_context_length']}")
        logger.info(f"Dry Run: {config['dry_run']}")
        logger.info(f"Build Type: {config['build_type']}")
        logger.info(f"Screenshot Mode: {config['screenshot_mode']}")
        logger.info(f"Headless Mode: {config['headless_mode']}")
        logger.info("=" * 80)

        # Validate setup
        self._validate_setup()

    def _validate_setup(self):
        """Validate that required files and directories exist."""
        if not self.docker_compose_file.exists():
            raise FileNotFoundError(
                f"Docker compose file not found: {self.docker_compose_file}"
            )

        if not self.app_codebase_dir.exists():
            raise FileNotFoundError(
                f"App codebase directory not found: {self.app_codebase_dir}"
            )

        if not self.openai_api_key or not self.openai_api_key.strip():
            raise ValueError("OPENAI_API_KEY is required but not provided")

        logger.info("✓ Containerized runner setup validated")

    def _execute_codex_container(self) -> Dict[str, Any]:
        """Execute the Codex agent inside the container."""
        try:
            logger.info("Executing Codex agent inside container...")

            # Create a temporary Python script for execution using config values
            agent_script = f"""#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, '/app')

try:
    # Import and configure the Codex agent
    from agent.codex_agent import CodexAgent

    # Create MCP config for container environment
    mcp_config = {{
        "server_url": "http://mcp-server:8000/mcp",
        "app_codebase_dir": "/tmp/{self.app_name}_app",
        "app_name": "{self.app_name}"
    }}

    # Create and run agent with config values
    agent = CodexAgent(
        max_iterations={self.config['max_iterations']},
        screenshot_enabled={self.config['screenshot_mode']},
        app_name="{self.app_name}",
        dry_run={self.config['dry_run']},
        app_server=None,
        timeout_ms=600000,
        mcp_config=mcp_config,
    )

    # Execute the agent
    result = agent.run()

    # Print results for capture
    print(f"AGENT_RESULT_STATUS: {{result.get('status', 'unknown')}}")
    print(f"AGENT_RESULT_TURNS: {{result.get('turns', 0)}}")
    if result.get('log_file'):
        print(f"AGENT_LOG_FILE: {{result['log_file']}}")

except Exception as e:
    print(f"AGENT_ERROR: {{str(e)}}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
"""

            # Write script to container
            write_script_cmd = [
                "docker",
                "exec",
                "-i",
                self.codex_container_name,
                "bash",
                "-c",
                "cat > /app/execute_agent.py && chmod +x /app/execute_agent.py",
            ]

            logger.info("Writing agent execution script to container...")
            script_process = subprocess.run(
                write_script_cmd,
                input=agent_script,
                text=True,
                capture_output=True,
            )

            if script_process.returncode != 0:
                logger.error(
                    f"Failed to write script to container: {script_process.stderr}"
                )
                return {
                    "status": "error",
                    "message": f"Failed to write script: {script_process.stderr}",
                    "container_execution": True,
                }

            # Execute the script inside the container
            cmd = [
                "docker",
                "exec",
                "-i",
                self.codex_container_name,
                "python3",
                "/app/execute_agent.py",
            ]

            logger.info(
                f"Executing: docker exec -i {self.codex_container_name} python3 /app/execute_agent.py"
            )

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                env={"OPENAI_API_KEY": self.openai_api_key},
            )

            # Stream output in real-time and capture results
            output_lines = []
            agent_status = "unknown"
            agent_turns = 0
            agent_log_file = None

            try:
                for line in process.stdout:
                    line = line.rstrip()
                    if line:
                        logger.info(f"[CODEX] {line}")
                        output_lines.append(line)

                        # Extract agent results from output
                        if line.startswith("AGENT_RESULT_STATUS:"):
                            agent_status = line.split(":", 1)[1].strip()
                        elif line.startswith("AGENT_RESULT_TURNS:"):
                            try:
                                agent_turns = int(line.split(":", 1)[1].strip())
                            except ValueError:
                                pass
                        elif line.startswith("AGENT_LOG_FILE:"):
                            agent_log_file = line.split(":", 1)[1].strip()
                            self.agent_log_file = agent_log_file
                        elif line.startswith("AGENT_ERROR:"):
                            agent_status = "error"

                # Wait for process completion
                exit_code = process.wait()

                logger.info(
                    f"Codex agent execution completed with exit code: {exit_code}"
                )

                return {
                    "status": agent_status if exit_code == 0 else "failed",
                    "exit_code": exit_code,
                    "output": "\n".join(output_lines),
                    "turns": agent_turns,
                    "log_file": agent_log_file,
                    "container_execution": True,
                }

            except KeyboardInterrupt:
                logger.info("Terminating Codex agent...")
                process.terminate()
                process.wait()
                raise

        except Exception as e:
            logger.error(f"Failed to execute Codex agent in container: {e}")
            return {
                "status": "error",
                "message": str(e),
                "container_execution": True,
            }

    def run(self) -> Dict[str, Any]:
        """
        Execute the containerized agent.

        Returns:
            Dictionary with execution results and metadata
        """
        logger.info("=" * 80)
        logger.info(
            "STARTING CONTAINERIZED CODEX AGENT"
        )  # ✅ Hardcoded since this is always Codex
        logger.info("=" * 80)
        logger.info(f"App: {self.app_name}")
        logger.info(f"Project Root: {self.project_root}")
        logger.info(
            f"Max Iterations: {self.config['max_iterations']}"
        )  # ✅ From config dict
        logger.info(f"Dry Run: {self.config['dry_run']}")  # ✅ From config dict

        try:
            mobile_runner = MobileCybenchRunner(self.app_name, self.config)
            mobile_runner.setup_emulator()
            mobile_runner.run_probes_checks()
            mobile_runner.setup_agent(True)
            mobile_runner.setup_app(True)

            # Execute agent
            result = self._execute_agent()

            return result

        except KeyboardInterrupt:
            logger.info("Execution interrupted by user")
            return {
                "status": "interrupted",
                "message": "Execution interrupted by user",
            }
        except Exception as e:
            logger.error(f"Containerized execution failed: {e}")
            return {
                "status": "error",
                "message": str(e),
            }
        finally:
            # Clean up containers
            self._cleanup_containers()

    def _execute_agent(self) -> Dict[str, Any]:
        """Execute the agent inside the container or using host-based approach."""
        logger.info("Executing codex agent...")

        return self._execute_codex_container()

    def _extract_logs(self):
        """Extract log files from containers before cleanup."""
        logger.info("Extracting log files from containers...")

        # Ensure logs directory exists
        os.makedirs("./logs", exist_ok=True)

        # Extract tool interaction log from codex container
        container_name = self.codex_container_name

        try:
            log_file = "/tmp/mobile_security_analysis.log"
            host_path = "./logs/mobile_security_analysis.log"

            cmd = ["docker", "cp", f"{container_name}:{log_file}", host_path]
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                logger.info(f"✓ Extracted log: {host_path}")
            else:
                logger.debug(f"Log file {log_file} not found in container")

        except Exception as e:
            logger.debug(f"Could not extract mobile_security_analysis.log: {e}")

        # Try to extract using captured filename first
        if self.agent_log_file:
            try:
                container_log_path = f"/app/{self.agent_log_file}"
                host_path = f"./logs/{self.agent_log_file}"

                cmd = [
                    "docker",
                    "cp",
                    f"{self.codex_container_name}:{container_log_path}",
                    host_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)

                if result.returncode == 0:
                    logger.info(f"✓ Extracted log: {host_path}")
                    return  # Successfully extracted, no need to search
                else:
                    logger.debug(
                        f"Agent log file {container_log_path} not found in container"
                    )

            except Exception as e:
                logger.debug(f"Could not extract agent log {self.agent_log_file}: {e}")

        # If no filename captured or extraction failed, search for agent logs
        # This is especially important for manual termination scenarios
        try:
            logger.info("Searching for agent run logs in container...")

            # List all log files in /app directory
            list_cmd = [
                "docker",
                "exec",
                self.codex_container_name,
                "find",
                "/app",
                "-name",
                "agent_run_*.log",
                "-type",
                "f",
            ]
            list_result = subprocess.run(
                list_cmd, capture_output=True, text=True, timeout=10
            )

            if list_result.returncode == 0 and list_result.stdout.strip():
                log_files = list_result.stdout.strip().split("\n")
                # Extract the most recent log file
                for container_log_path in log_files:
                    log_filename = os.path.basename(container_log_path)
                    host_path = f"./logs/{log_filename}"

                    cmd = [
                        "docker",
                        "cp",
                        f"{self.codex_container_name}:{container_log_path}",
                        host_path,
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True)

                    if result.returncode == 0:
                        logger.info(f"✓ Extracted agent log: {host_path}")
                    else:
                        logger.debug(f"Failed to extract {container_log_path}")
            else:
                logger.debug("No agent_run_*.log files found in container")

        except subprocess.TimeoutExpired:
            logger.debug("Timed out searching for agent logs")
        except Exception as e:
            logger.debug(f"Could not search for agent logs: {e}")

    def _cleanup_containers(self):
        """Clean up the containerized environment."""
        # Extract logs before cleanup
        self._extract_logs()

        logger.info("Cleaning up containers...")

        try:
            # Both codex and custom now use the same compose file without profiles
            cmd = [
                "docker",
                "compose",
                "-f",
                str(self.docker_compose_file),
                "down",
                "-v",
            ]

            subprocess.run(
                cmd,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=30,
            )

            logger.info("✓ Containers cleaned up")

        except subprocess.TimeoutExpired:
            logger.warning("Container cleanup timed out")
        except Exception as e:
            logger.warning(f"Container cleanup failed: {e}")

    def _create_dry_run_result(self) -> Dict[str, Any]:
        """Create a mock result for dry run mode."""
        logger.info("DRY RUN: Would execute containerized codex agent")
        logger.info(f"  App: {self.app_name}")
        logger.info("  Agent Type: codex")
        logger.info("  Security: Isolated environment")

        return {
            "status": "dry_run_completed",
            "app_name": self.app_name,
            "agent_type": "codex",
            "security_model": "isolated_containers",
        }


def load_config(config_path: Path) -> dict:
    """Load and validate configuration from JSON file"""
    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        sys.exit(1)

    try:
        with open(config_path, "r") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in config file: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error reading config file: {e}")
        sys.exit(1)

    # Validate required fields
    required_fields = [
        "server_access",
        "build_type",
        # TODO - implement adb allowlist based on this
        "adb_access",
        "max_iterations",
        "max_kali_message_tokens",
        "max_model_response_tokens",
        "max_context_length",
        "model",
        "screenshot_mode",
        "headless_mode",
        "dry_run",
    ]

    missing_fields = [field for field in required_fields if field not in config]
    if missing_fields:
        logger.error(f"Missing required config fields: {missing_fields}")
        sys.exit(1)

    # Validate field values
    valid_choices = {
        "build_type": ["source", "download-apk", "skip-apk"],
        "adb_access": ["none", "limited", "full"],
    }

    for field, choices in valid_choices.items():
        if config[field] not in choices:
            logger.error(
                f"Invalid value for {field}: {config[field]}. Must be one of: {choices}"
            )
            sys.exit(1)

    # Validate boolean fields
    bool_fields = ["server_access", "screenshot_mode", "headless_mode", "dry_run"]
    for field in bool_fields:
        if not isinstance(config[field], bool):
            logger.error(f"Field {field} must be a boolean (true/false)")
            sys.exit(1)

    # Validate integer fields
    int_fields = [
        "max_iterations",
        "max_kali_message_tokens",
        "max_model_response_tokens",
        "max_context_length",
    ]
    for field in int_fields:
        if not isinstance(config[field], int) or config[field] <= 0:
            logger.error(f"Field {field} must be a positive integer")
            sys.exit(1)

    # Validate model field
    if not isinstance(config["model"], str) or not config["model"].strip():
        logger.error("Field 'model' must be a non-empty string")
        sys.exit(1)

    logger.info("Configuration validation passed")
    return config


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="MobileCybench Runner - Orchestrates AI-driven mobile app security testing"
    )
    parser.add_argument(
        "app_name", help="Name of the app to test (must exist in apps/ directory)"
    )
    parser.add_argument(
        "config_file",
        nargs="?",
        default="runner_config.json",
        help="Path to JSON configuration file (default: runner_config.json)",
    )
    parser.add_argument(
        "--agent-type",
        choices=["custom", "codex"],
        default="custom",
        help="Type of agent to use: custom (default) or codex",
    )

    args = parser.parse_args()

    # Load configuration from file for both agent types
    config_file = args.config_file
    if not os.path.isabs(config_file):
        config_path = project_root / config_file
    else:
        config_path = Path(config_file)

    config = load_config(config_path)

    # Create appropriate runner based on agent type
    if args.agent_type == "codex":
        runner = ContainerizedCodexRunner(args.app_name, config)
    else:
        runner = MobileCybenchRunner(args.app_name, config)

    return runner.run()


if __name__ == "__main__":
    sys.exit(main())
