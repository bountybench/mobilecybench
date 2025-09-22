#!/usr/bin/env python3
"""
Mobile Cybench Runner Script

This script orchestrates the complete pipeline for running cybersecurity tests
on Android applications using AI agents.
"""

import argparse
import datetime
import json
import logging
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from selectors import EVENT_READ, DefaultSelector
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from utils.logger import logger
from utils.utils import get_app_metadata

# Create dedicated logger for tool interactions
tool_logger = logging.getLogger("MobileCyBench.Runner.ToolInteractions")
if not tool_logger.handlers:
    # Add file handler for tool interactions
    file_handler = logging.FileHandler("/tmp/mobile_security_analysis.log")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    tool_logger.addHandler(file_handler)
    tool_logger.setLevel(logging.INFO)

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


class ContainerizedCodexRunner:
    """Runner for executing Codex agent in isolated containers."""

    def __init__(
        self,
        app_name: str,
        project_root: str,
        openai_api_key: str,
        max_iterations: int = 30,
        dry_run: bool = False,
        agent_type: str = "codex",
    ):
        """
        Initialize the containerized runner.

        Args:
            app_name: Name of the mobile application to test
            project_root: Root directory of the MobileCyberBench project
            openai_api_key: OpenAI API key for Codex CLI
            max_iterations: Maximum number of analysis iterations
            dry_run: If True, show what would be done without executing
            agent_type: Type of agent to run (codex or custom)
        """
        self.app_name = app_name
        self.project_root = Path(project_root)
        self.openai_api_key = openai_api_key
        self.max_iterations = max_iterations
        self.dry_run = dry_run
        self.agent_type = agent_type

        # Paths
        self.docker_compose_file = self.project_root / "agent" / "docker-compose.yml"
        self.app_codebase_dir = self.project_root / "apps" / app_name / "codebase"

        # Container names
        self.codex_container_name = "codex-agent"
        self.mcp_container_name = "mcp-server"
        self.agent_log_file = None  # Store agent log filename

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

    def run(self) -> Dict[str, Any]:
        """
        Execute the containerized agent.

        Returns:
            Dictionary with execution results and metadata
        """
        logger.info("=" * 80)
        logger.info(f"STARTING CONTAINERIZED {self.agent_type.upper()} AGENT")
        logger.info("=" * 80)
        logger.info(f"App: {self.app_name}")
        logger.info(f"Project Root: {self.project_root}")
        logger.info(f"Max Iterations: {self.max_iterations}")
        logger.info(f"Agent Type: {self.agent_type}")
        logger.info(f"Dry Run: {self.dry_run}")
        logger.info("=" * 80)

        if self.dry_run:
            return self._create_dry_run_result()

        try:
            # Ensure shared network exists
            self._ensure_shared_network()

            # Start containers
            self._start_containers()

            # Wait for containers to be ready
            self._wait_for_containers()

            # Setup app (build and install APK)
            self._setup_app()

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

    def _ensure_shared_network(self):
        """Ensure the Docker network exists for container communication."""
        logger.info("Ensuring Docker network exists...")

        network_name = (
            "mobilecybench-isolated" if self.agent_type == "codex" else "shared_net"
        )

        try:
            # Check if network exists
            result = subprocess.run(
                ["docker", "network", "inspect", network_name],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                # Create network
                if network_name == "shared_net":
                    subprocess.run(
                        ["docker", "network", "create", network_name],
                        check=True,
                        capture_output=True,
                    )
                else:
                    subprocess.run(
                        [
                            "docker",
                            "network",
                            "create",
                            "--driver",
                            "bridge",
                            network_name,
                        ],
                        check=True,
                        capture_output=True,
                    )
                logger.info(f"✓ Created Docker network: {network_name}")
            else:
                logger.info(f"✓ Docker network already exists: {network_name}")

        except subprocess.CalledProcessError as e:
            logger.warning(f"Could not create Docker network: {e}")

    def _start_containers(self):
        """Start the containerized environment."""
        logger.info("Starting containerized environment...")

        env = os.environ.copy()
        env.update(
            {
                "APP_NAME": self.app_name,
                "OPENAI_API_KEY": self.openai_api_key,
            }
        )

        # Configure environment based on agent type
        if self.agent_type == "codex":
            env.update(
                {
                    "NETWORK_NAME": "mobilecybench-isolated",
                    "KALI_PRIVILEGED": "true",
                    "MCP_COMMAND": "python3 mcp_server.py",  # Skip ngrok for codex
                }
            )
            cmd = [
                "docker",
                "compose",
                "-f",
                str(self.docker_compose_file),
                "--profile",
                "codex",
                "up",
                "-d",
                "--build",
            ]
        else:
            env.update(
                {
                    "NETWORK_NAME": "shared_net",
                    "KALI_PRIVILEGED": "false",
                    "START_DIR": f"/tmp/{self.app_name}_app",
                }
            )
            cmd = [
                "docker",
                "compose",
                "-f",
                str(self.docker_compose_file),
                "up",
                "-d",
                "--build",
            ]

        logger.info(f"Command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_root,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            logger.info("✓ Containers started successfully")
            if result.stdout:
                logger.debug(f"Docker compose output: {result.stdout}")

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to start containers: {e}")
            if e.stdout:
                logger.error(f"Stdout: {e.stdout}")
            if e.stderr:
                logger.error(f"Stderr: {e.stderr}")
            raise

    def _wait_for_containers(self):
        """Wait for containers to be ready."""
        logger.info("Waiting for containers to be ready...")

        # Wait for MCP server container
        self._wait_for_container_health(self.mcp_container_name, timeout=60)

        # Wait for Codex container if running codex agent
        if self.agent_type == "codex":
            self._wait_for_container_health(self.codex_container_name, timeout=30)

        logger.info("✓ All containers are ready")

    def _wait_for_container_health(self, container_name: str, timeout: int = 60):
        """Wait for a specific container to be healthy."""
        logger.info(f"Waiting for container: {container_name}")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                result = subprocess.run(
                    [
                        "docker",
                        "inspect",
                        "--format",
                        "{{.State.Status}}",
                        container_name,
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )

                status = result.stdout.strip()
                if status == "running":
                    logger.info(f"✓ Container {container_name} is running")
                    return

                logger.debug(f"Container {container_name} status: {status}")

            except subprocess.CalledProcessError:
                logger.debug(f"Container {container_name} not found yet")

            time.sleep(2)

        raise TimeoutError(
            f"Container {container_name} did not become ready within {timeout}s"
        )

    def _setup_app(self):
        """Setup the mobile app: build and install APK."""
        logger.info("Setting up mobile application...")

        app_dir = self.project_root / "apps" / self.app_name

        # Check if setup.sh exists for this app
        setup_script = app_dir / "setup.sh"
        if not setup_script.exists():
            logger.warning(
                f"No setup.sh found for app {self.app_name}, skipping app setup"
            )
            return

        # Check if emulator is accessible from host
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if "device" not in result.stdout:
                logger.warning("No Android emulator detected on host")
                logger.warning("ADB commands may return generic responses")
                return

            logger.info("✓ Android emulator detected on host")

        except (
            subprocess.TimeoutExpired,
            subprocess.CalledProcessError,
            FileNotFoundError,
        ) as e:
            logger.warning(f"Could not check emulator status: {e}")
            return

        # Run the app setup script
        try:
            logger.info(f"Running app setup script: {setup_script}")
            result = subprocess.run(
                ["bash", "./setup.sh"],
                cwd=app_dir,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout for building
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

        except subprocess.TimeoutExpired:
            logger.error("App setup timed out after 5 minutes")
        except Exception as e:
            logger.error(f"App setup failed: {e}")

    def _execute_agent(self) -> Dict[str, Any]:
        """Execute the agent inside the container or using host-based approach."""
        logger.info(f"Executing {self.agent_type} agent...")

        if self.agent_type == "codex":
            return self._execute_codex_container()
        else:
            return self._execute_custom_agent()

    def _execute_codex_container(self) -> Dict[str, Any]:
        """Execute the Codex agent inside the container."""
        try:
            # Follow container logs
            cmd = ["docker", "logs", "-f", self.codex_container_name]

            logger.info("Following Codex agent execution...")
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            # Stream output in real-time
            output_lines = []
            try:
                for line in process.stdout:
                    line = line.rstrip()
                    if line:
                        logger.info(f"[CODEX] {line}")
                        output_lines.append(line)

                        # Extract agent log filename from output
                        if "Log file:" in line and "agent_run_" in line:
                            # Extract filename from log line
                            parts = line.split("Log file:")
                            if len(parts) > 1:
                                self.agent_log_file = parts[1].strip()
                                logger.debug(
                                    f"Captured agent log file: {self.agent_log_file}"
                                )

                # Wait for process completion
                process.wait()

                # Get container exit code
                container_result = subprocess.run(
                    [
                        "docker",
                        "inspect",
                        "--format",
                        "{{.State.ExitCode}}",
                        self.codex_container_name,
                    ],
                    capture_output=True,
                    text=True,
                )

                container_exit_code = (
                    int(container_result.stdout.strip())
                    if container_result.returncode == 0
                    else -1
                )

                return {
                    "status": "completed" if container_exit_code == 0 else "failed",
                    "exit_code": container_exit_code,
                    "output": "\\n".join(output_lines),
                    "container_logs": True,
                }

            except KeyboardInterrupt:
                logger.info("Terminating Codex agent...")
                process.terminate()
                process.wait()
                raise

        except Exception as e:
            logger.error(f"Failed to execute Codex agent: {e}")
            return {
                "status": "error",
                "message": str(e),
            }

    def _execute_custom_agent(self) -> Dict[str, Any]:
        """Execute custom agent using existing host-based approach."""
        logger.info("Running custom agent in containerized environment...")

        # Create a temporary config for custom agent
        config = {
            "server_access": True,
            "build_type": "source",
            "adb_access": "full",
            "max_iterations": self.max_iterations,
            "max_kali_message_tokens": 4000,
            "max_model_response_tokens": 8192,
            "max_context_length": 200000,
            "model": "gpt-4o",
            "screenshot_mode": False,
            "headless_mode": True,
            "dry_run": self.dry_run,
        }

        try:
            # Import and run custom agent
            from agent.custom_agent import CustomAgent
            from utils.utils import get_app_metadata

            metadata = get_app_metadata(self.app_name)

            agent = CustomAgent(
                model=config["model"],
                max_iterations=config["max_iterations"],
                max_model_response_tokens=config["max_model_response_tokens"],
                max_kali_message_tokens=config["max_kali_message_tokens"],
                max_context_length=config["max_context_length"],
                screenshot_enabled=config["screenshot_mode"],
                app_name=self.app_name,
                dry_run=config["dry_run"],
                app_server=metadata.get("app_server", None),
            )

            result = agent.run()
            return result

        except Exception as e:
            logger.error(f"Failed to execute custom agent: {e}")
            return {
                "status": "error",
                "message": str(e),
            }

    def _extract_logs(self):
        """Extract log files from containers before cleanup."""
        logger.info("Extracting log files from containers...")

        # Ensure logs directory exists
        os.makedirs("./logs", exist_ok=True)

        # Extract tool interaction log from appropriate container
        container_name = (
            self.codex_container_name
            if self.agent_type == "codex"
            else self.mcp_container_name
        )

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

        # Extract agent run log (for codex agent)
        if self.agent_type == "codex":
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
                    logger.debug(
                        f"Could not extract agent log {self.agent_log_file}: {e}"
                    )

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
        else:
            # For custom agent, try to extract any available logs
            try:
                logger.info("Searching for any available agent logs...")

                # Try to extract any logs from /tmp that might be agent-related
                list_cmd = [
                    "docker",
                    "exec",
                    self.mcp_container_name,
                    "find",
                    "/tmp",
                    "-name",
                    "*agent*.log",
                    "-o",
                    "-name",
                    "*run*.log",
                    "-type",
                    "f",
                ]
                list_result = subprocess.run(
                    list_cmd, capture_output=True, text=True, timeout=10
                )

                if list_result.returncode == 0 and list_result.stdout.strip():
                    log_files = list_result.stdout.strip().split("\n")
                    for container_log_path in log_files:
                        if (
                            container_log_path != "/tmp/mobile_security_analysis.log"
                        ):  # Skip already extracted
                            log_filename = os.path.basename(container_log_path)
                            host_path = f"./logs/{log_filename}"

                            cmd = [
                                "docker",
                                "cp",
                                f"{self.mcp_container_name}:{container_log_path}",
                                host_path,
                            ]
                            result = subprocess.run(cmd, capture_output=True, text=True)

                            if result.returncode == 0:
                                logger.info(f"✓ Extracted additional log: {host_path}")
                            else:
                                logger.debug(f"Failed to extract {container_log_path}")

            except subprocess.TimeoutExpired:
                logger.debug("Timed out searching for additional logs")
            except Exception as e:
                logger.debug(f"Could not search for additional logs: {e}")

    def _cleanup_containers(self):
        """Clean up the containerized environment."""
        # Extract logs before cleanup
        self._extract_logs()

        logger.info("Cleaning up containers...")

        try:
            if self.agent_type == "codex":
                cmd = [
                    "docker",
                    "compose",
                    "-f",
                    str(self.docker_compose_file),
                    "--profile",
                    "codex",
                    "down",
                    "-v",
                ]
            else:
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
        logger.info(f"DRY RUN: Would execute containerized {self.agent_type} agent")
        logger.info(f"  App: {self.app_name}")
        logger.info(f"  Agent Type: {self.agent_type}")
        logger.info("  Security: Isolated environment")

        return {
            "status": "dry_run_completed",
            "app_name": self.app_name,
            "agent_type": self.agent_type,
            "security_model": "isolated_containers",
        }


class MobileCybenchRunner:
    def __init__(self, app_name: str, config: dict, agent_type: str = "custom"):
        self.app_name = app_name
        self.config = config
        self.agent_type = agent_type
        self.project_root = project_root
        self.app_dir = self.project_root / "apps" / app_name
        self.agent_dir = self.project_root / "agent"
        self.cmd = CommandExecutor()

        logger.info("=" * 80)
        logger.info("MobileCybench Runner Started")
        logger.info(f"App: {app_name}")
        logger.info(f"Agent Type: {agent_type}")
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
        required_scripts = ["setup_app_source.sh", "setup.sh", "run_checks.sh"]
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
            "Emulator setup started, waiting for it to be ready while building the app..."
        )

    def setup_app(self):
        """Build and install the app"""
        logger.info("Building the app from source")
        logger.info("=" * 60)
        logger.info("SETTING UP APP SOURCE")
        logger.info("=" * 60)
        try:
            self.cmd.run("./setup_app_source.sh", cwd=self.app_dir, live_output=True)
        except subprocess.CalledProcessError as e:
            self._exit_with_error(f"Failed to setup app source: {e}")

        # Check emulator is ready (this will wait until device is ready)
        logger.info("=" * 60)
        logger.info("CHECKING EMULATOR STATUS")
        logger.info("=" * 60)
        logger.info("Checking emulator status...")
        try:
            self.cmd.run("./check_device.sh", cwd=self.project_root, live_output=True)
        except subprocess.CalledProcessError as e:
            self._exit_with_error(f"Failed to check emulator status: {e}")

        # Setup app (setup backend, install apk, etc.)
        logger.info("=" * 60)
        logger.info("BUILDING AND INSTALLING APP")
        logger.info("=" * 60)
        logger.info("Building and installing app...")
        try:
            self.cmd.run("./setup.sh", cwd=self.app_dir, live_output=True)
        except subprocess.CalledProcessError as e:
            self._exit_with_error(f"Failed to build and install app: {e}")

        logger.info("App setup completed")

    def setup_agent(self):
        """Configure agent environment and start services"""
        logger.info("=" * 60)
        logger.info("SETTING UP AGENT ENVIRONMENT")
        logger.info("=" * 60)
        logger.info("Setting up agent environment...")

        self._setup_env_file()
        self._create_docker_network()
        self._start_containers()
        self._copy_codebase_to_kali()

        logger.info("Agent environment setup completed")
        logger.info("✓ Agent environment setup completed")

    def _setup_env_file(self):
        """Handle .env file creation/update for OpenAI API key"""
        logger.info("Setting up environment file...")

        # Check for .env file in project root first, then agent directory
        project_env_file = self.project_root / ".env"
        agent_env_file = self.agent_dir / ".env"

        env_file = None
        if project_env_file.exists():
            env_file = project_env_file
        elif agent_env_file.exists():
            env_file = agent_env_file

        # Load existing .env if found
        if env_file:
            logger.info(f"Loading existing environment from {env_file}")
            load_dotenv(dotenv_path=env_file, override=False)
        else:
            logger.error(
                f"No existing .env file found at {project_env_file} or {agent_env_file}. Please create one with OPENAI_API_KEY."
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

    def _start_containers(self):
        """Start MCP server and Kali container"""
        logger.info("Starting containers...")
        logger.info("Starting MCP server and Kali container...")

        # Set environment variable for docker-compose
        env = os.environ.copy()
        start_dir = f"/tmp/{self.app_name}_app"
        env["START_DIR"] = start_dir

        logger.info(f"Setting START_DIR environment variable: {start_dir}")
        logger.info(f"Environment variable START_DIR set to: {start_dir}")
        logger.info("Starting containers with docker compose...")

        try:
            self.cmd.run("docker compose up -d", cwd=self.agent_dir, env=env)
        except subprocess.CalledProcessError as e:
            logger.error(
                f"Docker-compose failed: {e.stderr if hasattr(e, 'stderr') else e}"
            )
            self._exit_with_error("Failed to start containers")

        logger.info("✓ Containers started successfully")
        logger.info("Containers started successfully")

        logger.info("Waiting for containers to initialize...")
        logger.info("Waiting for containers to initialize...")
        time.sleep(5)
        # TODO: Implement a more robust check to ensure services are up and running
        # Container healt

        # Check container status
        logger.info("Checking container status...")
        try:
            result = self.cmd.run("docker compose ps", cwd=self.agent_dir)
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to check container status: {e}")
            result = None

        if result:
            logger.info("Container Status:")
            logger.info(result.stdout)
            logger.info(f"Container status:\n{result.stdout}")

            # Verify specific containers are running
            if "mcp-server" in result.stdout and "kali-container" in result.stdout:
                logger.info("✓ Both MCP server and Kali container are running")
                logger.info("Both MCP server and Kali container confirmed running")
            else:
                logger.warning("Some containers may not be running properly")
                logger.warning("⚠ Warning: Some containers may not be running properly")

    def _copy_codebase_to_kali(self):
        """Copy app codebase to Kali container"""
        logger.info("Copying app codebase to Kali container...")
        logger.info("Copying app codebase to Kali container...")

        source_path = self.app_dir / "codebase"
        container_name = "kali-container"
        target_path = f"/tmp/{self.app_name}_app"
        # TODO: Make target path to be the directory that the agent has access to

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
        """Run the AI agent - supports both custom and codex agent types"""
        logger.info("=" * 60)
        logger.info(f"RUNNING {self.agent_type.upper()} AGENT")
        logger.info("=" * 60)
        logger.info(f"Starting {self.agent_type} agent execution...")

        try:
            if self.agent_type == "custom":
                # Import the CustomAgent class
                from agent.custom_agent import CustomAgent

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

            elif self.agent_type == "codex":
                # Import the CodexAgent class
                from agent.codex_agent import CodexAgent
                from utils.mcp_utils import get_mcp_server_config

                logger.info("Initializing codex agent...")
                logger.info("Creating CodexAgent instance")

                # Create MCP config with app context for proper working directory
                mcp_config = get_mcp_server_config(
                    project_root=str(self.project_root), app_name=self.app_name
                )

                agent = CodexAgent(
                    max_iterations=self.config["max_iterations"],
                    max_model_response_tokens=self.config.get(
                        "codex_max_tokens", self.config["max_model_response_tokens"]
                    ),
                    max_context_length=self.config["max_context_length"],
                    screenshot_enabled=self.config.get("screenshot_mode", False),
                    app_name=self.app_name,
                    dry_run=self.config["dry_run"],
                    app_server=self.metadata.get("app_server", None),
                    timeout_ms=self.config.get("codex_timeout_ms", 600000),
                    mcp_config=mcp_config,
                )

            else:
                raise ValueError(f"Unknown agent type: {self.agent_type}")

            logger.info("Running agent...")
            logger.info("Executing agent.run()")

            # This can take a while for actual LLM calls
            result = agent.run()

            # Log and display results
            logger.info("Agent execution completed")
            logger.info(f"Agent result: {result}")

            # Log tool interactions summary for review
            if hasattr(agent, "get_tool_interactions_summary"):
                tool_summary = agent.get_tool_interactions_summary()
                if tool_summary:
                    tool_logger.info(
                        "=== AGENT EXECUTION TOOL INTERACTIONS SUMMARY ==="
                    )
                    tool_logger.info(f"Total iterations: {result.get('turns', 0)}")
                    tool_logger.info(f"Agent type: {self.agent_type}")
                    tool_logger.info(f"App: {self.app_name}")
                    for interaction in tool_summary:
                        tool_logger.info(f"Tool interaction: {interaction}")

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
            tool_logger.info(f"=== COMPLETED ANALYSIS FOR {self.app_name} ===")
            tool_logger.info(f"Results logged to: {result.get('log_file', 'None')}")

            return result

        except Exception as e:
            logger.error(f"Error running {self.agent_type} agent: {e}")
            logger.error(f"ERROR: Failed to run {self.agent_type} agent: {e}")
            return {
                "status": f"error: {str(e)}",
                "turns": 0,
                "final_message": None,
                "log_file": None,
            }

    def run_probes_checks(self):
        """Run the evaluation checks"""
        logger.info("=" * 60)
        logger.info("RUNNING PROBE CHECKS")
        logger.info("=" * 60)
        logger.info("Running probe checks...")

        # Run the checks
        try:
            result = self.cmd.run("./run_checks.sh", cwd=self.app_dir, check=False)
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
            self.run_probes_checks()

            self.setup_agent()
            self.run_agent()

            self.run_probes_checks()

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
        "build_type": ["source", "apk"],
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
    parser.add_argument(
        "--containerized",
        action="store_true",
        help="Run in containerized mode (isolated Docker containers)",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root directory (default: current directory)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=30,
        help="Maximum iterations for containerized mode (default: 30)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without executing (containerized mode only)",
    )

    args = parser.parse_args()

    # Handle containerized mode
    if args.containerized:
        # Get API key from environment
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.error(
                "OPENAI_API_KEY environment variable is required for containerized mode"
            )
            sys.exit(1)

        # Create and run containerized agent
        runner = ContainerizedCodexRunner(
            app_name=args.app_name,
            project_root=args.project_root,
            openai_api_key=api_key,
            max_iterations=args.max_iterations,
            dry_run=args.dry_run,
            agent_type=args.agent_type,
        )

        result = runner.run()

        # Print final status
        logger.info("=" * 80)
        logger.info(f"EXECUTION COMPLETED: {result.get('status', 'unknown')}")
        logger.info("=" * 80)

        if result.get("status") == "error":
            sys.exit(1)

        return 0

    # Handle regular (host-based) mode
    else:
        # Load configuration from file
        # If relative path, make it relative to the script directory
        config_file = args.config_file
        if not os.path.isabs(config_file):
            config_path = project_root / config_file
        else:
            config_path = Path(config_file)

        config = load_config(config_path)

        # Override dry_run from command line if provided
        if args.dry_run:
            config["dry_run"] = args.dry_run

        # Create and run the runner
        runner = MobileCybenchRunner(args.app_name, config, args.agent_type)
        return runner.run()


if __name__ == "__main__":
    sys.exit(main())
