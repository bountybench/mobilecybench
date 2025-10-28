#!/usr/bin/env python3

import argparse
import datetime
import os
import shlex
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from agent.agent_setup import AgentEnvironment
from agent.mcp.direct_tool_executor import MCPToolExecutor
from models.config import RunnerConfig
from utils.command_executor import CommandExecutor
from utils.emulator_manager import EmulatorManager
from utils.logger import logger, logger_manager
from utils.utils import get_app_metadata

load_dotenv()
project_root = Path(__file__).parent

EMULATOR_BOOT_TIMEOUT_SECONDS = 300  # 5 minutes
BUILD_COMMAND_TIMEOUT = 600  # 10 minutes
DUMMY_LOG_FILENAME = "dummy_log.txt"


def log_banner(message: str, width: int = 60):
    logger.info("=" * width)
    logger.info(message.center(width))
    logger.info("=" * width)


class MobileCybenchRunner:
    def __init__(self, app_name: str, config: RunnerConfig, agent_only: bool = False):
        self.app_name = Path(app_name).name
        self.config = config
        self.agent_only = agent_only
        self.project_root = project_root
        self.app_dir = self.project_root / "apps" / self.app_name
        self.agent_dir = self.project_root / "agent"
        self.cmd = CommandExecutor()
        self.emulator = None

        log_banner("MobileCybench Runner Started", width=80)
        logger.info(f"App: {app_name}")
        logger.info(f"Configuration: {config.model_dump_json(indent=2)}")
        logger.info(f"Timestamp: {datetime.datetime.now()}")

    def _exit_with_error(self, message: str):
        """Log error and exit"""
        logger.error(message)
        logger.error("Runner execution failed. Check log for details.")
        # TODO: a conditional cleanup based on how far we got until failure
        # for example, if we fail after starting containers, we should stop them
        sys.exit(1)

    def _validate_api_key(self):
        """Validate OpenAI API key early in the pipeline"""
        logger.info("Validating OpenAI API key...")

        # Load .env file from agent directory
        env_file = self.agent_dir / ".env"
        if env_file.exists():
            logger.info(f"Loading existing environment from {env_file}")
            load_dotenv(dotenv_path=env_file, override=False)
        else:
            self._exit_with_error(
                f"No existing .env file found at {env_file}. Please create one with OPENAI_API_KEY."
            )

        # Check if API key exists in environment
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            self._exit_with_error("OPENAI_API_KEY not found in environment or .env")

        # Validate the API key works by making a test call
        try:
            from agent.model_providers import get_model_provider

            provider = get_model_provider("openai")
            provider.validate()
            logger.info("✓ OpenAI API key validated successfully")
        except Exception as e:
            self._exit_with_error(f"OpenAI API key validation failed: {e}")

    def validate_input(self):
        """Validate app name and required files"""
        logger.info("Validating input...")

        # Validate API key early (before starting emulator and app servers)
        if not self.config.dry_run:
            self._validate_api_key()

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
        required_scripts = ["setup.sh"]

        if not self.agent_only:  # Check for build scripts if not in agent_only mode
            if self.config.build_type == "source":
                required_scripts.append("setup_app_source.sh")
            elif self.config.build_type == "download-apk":
                required_scripts.append("setup_app_apklink.sh")
            elif self.config.build_type == "skip-apk":
                possible_setup_scripts = ["setup_app_source.sh", "setup_app_apklink.sh"]
                # do not allow skip-apk if neither script exists
                if not any(
                    (self.app_dir / script).exists()
                    for script in possible_setup_scripts
                ):
                    self._exit_with_error(
                        f"At least one setup script required for build_type 'skip-apk' not found: {possible_setup_scripts}"
                    )
            else:
                self._exit_with_error(
                    f"Unsupported Build Type Detected: {self.config.build_type}"
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

    def setup_app(self):
        """APK Handling, App Backend Setup, and App Installation"""
        if self.config.build_type == "skip-apk":
            log_banner("SKIPPING APK HANDLING STEP")
        elif self.config.build_type == "download-apk":
            log_banner("FETCHING APK USING APKLINK")
            try:
                self.cmd.run_with_progress(
                    "bash ./setup_app_apklink.sh",
                    timeout=BUILD_COMMAND_TIMEOUT,
                    message="Downloading APK",
                    cwd=self.app_dir,
                )
            except subprocess.CalledProcessError as e:
                self._exit_with_error(
                    f"Failed to setup app APK with setup_app_apklink.sh: {e}"
                )
        else:  # source
            log_banner("BUILDING APK FROM SOURCE")
            try:
                self.cmd.run_with_progress(
                    "bash ./setup_app_source.sh",
                    timeout=BUILD_COMMAND_TIMEOUT,
                    message="Building APK from source",
                    cwd=self.app_dir,
                )
            except subprocess.CalledProcessError as e:
                self._exit_with_error(
                    f"Failed to setup app source with setup_app_source.sh: {e}"
                )

        # ensures emulator is fully booted and ready
        try:
            self.emulator.wait_until_ready(timeout=EMULATOR_BOOT_TIMEOUT_SECONDS)
            logger.info("Emulator booted successfully")
        except Exception as e:
            self._exit_with_error(f"Failed to wait for emulator to finish booting: {e}")

        if not self.emulator.check_status():
            self._exit_with_error("Emulator status check failed")
        logger.info("Emulator status verified")

        # Setup app (setup backend, install apk, etc.)
        log_banner(
            "SETTING UP THE BACKEND(RUNTIME SERVERS, DATABASES, SEEDS, etc.) AND INSTALLING APK"
        )
        try:
            self.cmd.run_with_progress(
                "bash ./setup.sh",
                timeout=BUILD_COMMAND_TIMEOUT,
                message="Setting up backend and installing APK",
                cwd=self.app_dir,
            )
        except subprocess.CalledProcessError as e:
            self._exit_with_error(f"Failed to setup app: {e}")

        logger.info("Injecting security flags...")
        try:
            inject_flags_path = project_root / "inject_flags.sh"
            self.cmd.run(
                f"bash {inject_flags_path}",
                cwd=self.app_dir,
                timeout=30,
            )
            logger.info("✓ Flags injected successfully")
        except subprocess.CalledProcessError as e:
            self._exit_with_error(f"Failed to inject security flags: {e}")
        logger.info("App setup completed")

    def setup_agent(self):
        """Configure agent environment and start services"""
        log_banner("SETTING UP AGENT ENVIRONMENT")

        if not self.config.dry_run:
            self._setup_env_file()
        self._create_docker_network()

        # Setup agent kali environment
        agent_env = AgentEnvironment(
            app_dir=self.app_dir,
            docker_networks=["shared_net"],
            image_name=self.config.agent_image,
            env={"ANDROID_ADB_SERVER_PORT": "5037"},
            commit_id=self.metadata.get("commit_version"),
        )
        agent_env.setup()
        self.agent_env = agent_env

        self._start_containers()

        logger.info("Agent environment setup completed")

    def _setup_env_file(self):
        """Load environment file for OpenAI API key (already validated)"""
        logger.info("Loading environment file...")

        env_file = self.agent_dir / ".env"
        # We know the file exists and key is valid from earlier validation
        load_dotenv(dotenv_path=env_file, override=False)
        api_key = os.getenv("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = api_key
        logger.info("✓ Environment loaded with OPENAI_API_KEY")

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

    def _validate_mcp_server(self):
        """Validate MCP server is functional by testing command execution"""
        logger.info("Validating MCP server with 'ls' command...")

        mcp_executor = MCPToolExecutor()
        result = mcp_executor.call_tool("execute_command", "ls /app")
        response = (
            result.get("result", {}).get("structuredContent", {}).get("response", "")
        )

        if "codebase" not in response:
            self._exit_with_error(
                "MCP server validation failed: 'codebase' directory not found"
            )

        logger.info("✓ MCP server validation passed: 'codebase' directory found")

    def _start_containers(self):
        """Start MCP server and Kali container"""
        logger.info("Starting MCP server and Kali container...")

        env = os.environ.copy()

        try:
            self.cmd.run("docker compose up -d --wait", cwd=self.agent_dir, env=env)
        except subprocess.CalledProcessError as e:
            logger.error(
                f"Docker-compose failed: {e.stderr if hasattr(e, 'stderr') else e}"
            )
            self._exit_with_error("Failed to start containers")

        # Validate MCP server functionality
        self._validate_mcp_server()

        try:
            result = self.cmd.run("docker compose ps", cwd=self.agent_dir)
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to check container status: {e}")
            result = None

        if result:
            logger.debug(f"Container status:\n{result.stdout}")

            # Verify specific containers are running
            if "mcp-server" in result.stdout:
                logger.info("✓ Both MCP server and Kali container are running")
            else:
                logger.warning("⚠ Warning: Some containers may not be running properly")

    def run_agent(self):
        """Run the custom agent - custom_agent.py"""
        log_banner("RUNNING CUSTOM AGENT")

        try:
            # Import the CustomAgent class
            from agent.custom_agent import CustomAgent

            logger.info("Initializing CustomAgent...")

            agent = CustomAgent(
                model=self.config.model,
                max_iterations=self.config.max_iterations,
                max_model_response_tokens=self.config.max_model_response_tokens,
                max_kali_message_tokens=self.config.max_kali_message_tokens,
                max_context_length=self.config.max_context_length,
                screenshot_enabled=self.config.screenshot_mode,
                app_name=self.app_name,
                app_server=getattr(self, "metadata", {}).get(
                    "app_server", None
                ),  # default to None if in agent_only mode
                # TODO - create proper dry run mode
                # https://github.com/bountybench/mobilecybench/issues/322
                dry_run=self.config.dry_run,
                system_prompt=self.config.custom_system_prompt,
            )

            # This can take a while for actual LLM calls
            result = agent.run()

            log_banner("AGENT EXECUTION RESULTS")
            logger.info(f"Status: {result.get('status', 'Unknown')}")
            logger.info(f"Turns: {result.get('turns', 0)}")
            logger.info(f"Log file: {result.get('log_file', 'None')}")

            if result.get("final_message"):
                logger.info("Final Message:")
                logger.info(f"  {result['final_message']}")

            return result

        except Exception as e:
            logger.error(f"Failed to run custom agent: {e}")
            return {
                "status": f"error: {str(e)}",
                "turns": 0,
                "final_message": None,
                "log_file": None,
            }

    def run_probes_checks(self, log_file_path: Path):
        log_banner("RUNNING PROBE CHECKS")

        app_relative_path = f"apps/{self.app_name}"
        command = f"bash ./run_checks.sh {shlex.quote(app_relative_path)}"

        log_path = Path(log_file_path)
        if log_path.exists() and log_path.is_file():
            relative_log_path = Path("../../") / log_path
            command = f"{command} {shlex.quote(str(relative_log_path))}"
            logger.info(f"Passing log file to probe checks: {relative_log_path}")
        else:
            logger.error(
                f"Log file path does not exist: {log_path}, running without it. This may limit the quality of the probes checks."
            )
        try:
            result = self.cmd.run(command, cwd=self.project_root, check=False)
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
        else:
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

    def _run_agent_pipeline(self):
        """Run probe checks, agent setup, and agent execution"""
        dummy_log_path = Path(DUMMY_LOG_FILENAME)
        if not dummy_log_path.exists():
            dummy_log_path.touch()
        self.run_probes_checks(log_file_path=dummy_log_path)

        self.setup_agent()
        self.run_agent()

        agent_log_filename = logger_manager.get_agent_log_file_name()
        log_path = Path(agent_log_filename)
        logger.info(f"Agent log file path: {log_path}")
        self.run_probes_checks(log_file_path=log_path)

    def run(self):
        try:
            self.validate_input()

            if not self.agent_only:
                log_banner("SETTING UP ANDROID EMULATOR")
                sdk_version = (
                    self.metadata.get("sdk") if hasattr(self, "metadata") else None
                )
                with EmulatorManager(
                    docker_mode=self.config.docker_mode,
                    project_root=self.project_root,
                    sdk_version=sdk_version,
                    app_name=self.app_name,
                ) as emulator:
                    self.emulator = emulator
                    self.emulator.start_in_background()
                    logger.info("Emulator started in the background . . .")

                    self.setup_app()
                    self._run_agent_pipeline()
            else:
                self._run_agent_pipeline()

            log_banner(f"PIPELINE COMPLETED SUCCESSFULLY FOR <<{self.app_name}>>")
            return 0

        except KeyboardInterrupt:
            logger.info("Runner interrupted by user")
            return 1
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return 1
        finally:
            pass
            # TODO clean up


def main():
    parser = argparse.ArgumentParser(
        description="MobileCybench Runner - Orchestrates AI-driven mobile app security testing"
    )

    # Add agent_only as a flag
    parser.add_argument(
        "--agent-only",
        action="store_true",
        dest="agent_only",
        help="Run only the agent, skipping emulator setup and app setup. Optional.",
    )

    parser.add_argument(
        "app_name",
        help="Name of the app to test (must exist in apps/ directory). Required.",
    )

    # Add config_file as optional
    parser.add_argument(
        "config_file",
        nargs="?",
        default="runner_config.json",
        help="Path to JSON configuration file (default: runner_config.json)",
    )

    args = parser.parse_args()

    # Load configuration from file
    # If relative path, make it relative to the script directory
    config_file = args.config_file
    if not os.path.isabs(config_file):
        config_path = project_root / config_file
    else:
        config_path = Path(config_file)

    config = RunnerConfig.from_file(config_path)

    runner = MobileCybenchRunner(args.app_name, config, args.agent_only)
    return runner.run()


if __name__ == "__main__":
    sys.exit(main())
