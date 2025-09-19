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
from typing import Dict, List, Optional

from dotenv import load_dotenv

from utils.logger import logger
from utils.utils import get_app_metadata
import logging

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
                    model=self.config.get("codex_model", self.config["model"]),
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

    args = parser.parse_args()

    # Load configuration from file
    # If relative path, make it relative to the script directory
    config_file = args.config_file
    if not os.path.isabs(config_file):
        config_path = project_root / config_file
    else:
        config_path = Path(config_file)

    config = load_config(config_path)

    # Create and run the runner
    runner = MobileCybenchRunner(args.app_name, config, args.agent_type)
    return runner.run()


if __name__ == "__main__":
    sys.exit(main())
