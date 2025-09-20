#!/usr/bin/env python3
"""
Containerized Runner for MobileCyberBench Codex Agent

This runner executes the Codex agent in an isolated container environment,
providing better security and isolation compared to running directly on the host.

Key features:
- Complete isolation of app source code and Codex agent
- Secure container-to-container networking
- API key isolation via environment variables
- Clean separation between development and testing environments
"""

import os
import subprocess
import sys
import time
import signal
import logging
from pathlib import Path
from typing import Dict, Optional, Any
import yaml
import json

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not available, skip loading
    pass

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("ContainerizedRunner")


class ContainerizedCodexRunner:
    """Runner for executing Codex agent in isolated containers."""

    def __init__(
        self,
        app_name: str,
        project_root: str,
        openai_api_key: str,
        max_iterations: int = 30,
        dry_run: bool = False,
    ):
        """
        Initialize the containerized runner.

        Args:
            app_name: Name of the mobile application to test
            project_root: Root directory of the MobileCyberBench project
            openai_api_key: OpenAI API key for Codex CLI
            max_iterations: Maximum number of analysis iterations
            dry_run: If True, show what would be done without executing
        """
        self.app_name = app_name
        self.project_root = Path(project_root)
        self.openai_api_key = openai_api_key
        self.max_iterations = max_iterations
        self.dry_run = dry_run

        # Paths
        self.docker_compose_file = self.project_root / "agent" / "docker-compose-isolated.yml"
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
        Execute the containerized Codex agent.

        Returns:
            Dictionary with execution results and metadata
        """
        logger.info("=" * 80)
        logger.info("STARTING CONTAINERIZED CODEX AGENT")
        logger.info("=" * 80)
        logger.info(f"App: {self.app_name}")
        logger.info(f"Project Root: {self.project_root}")
        logger.info(f"Max Iterations: {self.max_iterations}")
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

            # Execute Codex agent
            result = self._execute_codex_agent()

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

        try:
            # Check if network exists
            result = subprocess.run(
                ["docker", "network", "inspect", "shared_net"],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                # Create network
                subprocess.run(
                    ["docker", "network", "create", "shared_net"],
                    check=True,
                    capture_output=True,
                )
                logger.info("✓ Created Docker network: shared_net")
            else:
                logger.info("✓ Docker network already exists: shared_net")

        except subprocess.CalledProcessError as e:
            logger.warning(f"Could not create Docker network: {e}")

    def _start_containers(self):
        """Start the containerized environment."""
        logger.info("Starting containerized environment...")

        env = os.environ.copy()
        env.update({
            "APP_NAME": self.app_name,
            "OPENAI_API_KEY": self.openai_api_key,
        })

        cmd = [
            "docker", "compose",
            "-f", str(self.docker_compose_file),
            "up", "-d", "--build"
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

        # Wait for Codex container to be running
        self._wait_for_container_health(self.codex_container_name, timeout=30)

        logger.info("✓ All containers are ready")

    def _wait_for_container_health(self, container_name: str, timeout: int = 60):
        """Wait for a specific container to be healthy."""
        logger.info(f"Waiting for container: {container_name}")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                result = subprocess.run(
                    ["docker", "inspect", "--format", "{{.State.Status}}", container_name],
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

        raise TimeoutError(f"Container {container_name} did not become ready within {timeout}s")

    def _setup_app(self):
        """Setup the mobile app: build and install APK."""
        logger.info("Setting up mobile application...")

        app_dir = self.project_root / "apps" / self.app_name

        # Check if setup.sh exists for this app
        setup_script = app_dir / "setup.sh"
        if not setup_script.exists():
            logger.warning(f"No setup.sh found for app {self.app_name}, skipping app setup")
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

        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError) as e:
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

    def _execute_codex_agent(self) -> Dict[str, Any]:
        """Execute the Codex agent inside the container."""
        logger.info("Executing Codex agent...")

        try:
            # Follow container logs
            cmd = [
                "docker", "logs", "-f", self.codex_container_name
            ]

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
                                logger.debug(f"Captured agent log file: {self.agent_log_file}")

                # Wait for process completion
                return_code = process.wait()

                # Get container exit code
                container_result = subprocess.run(
                    ["docker", "inspect", "--format", "{{.State.ExitCode}}", self.codex_container_name],
                    capture_output=True,
                    text=True,
                )

                container_exit_code = int(container_result.stdout.strip()) if container_result.returncode == 0 else -1

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

    def _extract_logs(self):
        """Extract log files from containers before cleanup."""
        logger.info("Extracting log files from containers...")

        # Ensure logs directory exists
        os.makedirs("./logs", exist_ok=True)

        # Extract tool interaction log
        try:
            log_file = "/tmp/mobile_security_analysis.log"
            host_path = "./logs/mobile_security_analysis.log"

            cmd = ["docker", "cp", f"{self.codex_container_name}:{log_file}", host_path]
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                logger.info(f"✓ Extracted log: {host_path}")
            else:
                logger.debug(f"Log file {log_file} not found in container")

        except Exception as e:
            logger.debug(f"Could not extract mobile_security_analysis.log: {e}")

        # Extract agent run log using captured filename
        if self.agent_log_file:
            try:
                container_log_path = f"/app/{self.agent_log_file}"
                host_path = f"./logs/{self.agent_log_file}"

                cmd = ["docker", "cp", f"{self.codex_container_name}:{container_log_path}", host_path]
                result = subprocess.run(cmd, capture_output=True, text=True)

                if result.returncode == 0:
                    logger.info(f"✓ Extracted log: {host_path}")
                else:
                    logger.debug(f"Agent log file {container_log_path} not found in container")

            except Exception as e:
                logger.debug(f"Could not extract agent log {self.agent_log_file}: {e}")
        else:
            logger.debug("No agent log filename was captured during execution")

    def _cleanup_containers(self):
        """Clean up the containerized environment."""
        # Extract logs before cleanup
        self._extract_logs()

        logger.info("Cleaning up containers...")

        try:
            cmd = [
                "docker", "compose",
                "-f", str(self.docker_compose_file),
                "down", "-v"
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
        logger.info("DRY RUN: Would execute containerized Codex agent")
        logger.info(f"  App: {self.app_name}")
        logger.info(f"  Container: {self.codex_container_name}")
        logger.info(f"  Security: Isolated environment")

        return {
            "status": "dry_run_completed",
            "app_name": self.app_name,
            "container_name": self.codex_container_name,
            "security_model": "isolated_containers",
        }


def main():
    """Main entry point for containerized runner."""
    import argparse

    parser = argparse.ArgumentParser(description="Run Codex agent in isolated containers")
    parser.add_argument("--app", required=True, help="App name to test")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument("--max-iterations", type=int, default=30, help="Maximum iterations")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")

    args = parser.parse_args()

    # Get API key from environment
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY environment variable is required")
        sys.exit(1)

    # Create and run containerized agent
    runner = ContainerizedCodexRunner(
        app_name=args.app,
        project_root=args.project_root,
        openai_api_key=api_key,
        max_iterations=args.max_iterations,
        dry_run=args.dry_run,
    )

    result = runner.run()

    # Print final status
    logger.info("=" * 80)
    logger.info(f"EXECUTION COMPLETED: {result.get('status', 'unknown')}")
    logger.info("=" * 80)

    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()