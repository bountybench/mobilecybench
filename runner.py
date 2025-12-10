#!/usr/bin/env python3

import argparse
import datetime
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from agent.agent_setup import AgentEnvironment
from agent.mcp.direct_tool_executor import MCPToolExecutor
from models.config import RunnerConfig
from utils.command_executor import CommandExecutor
from utils.emulator_manager import EmulatorManager
from utils.logger import logger, logger_manager
from utils.time_tracker import time_tracker
from utils.utils import get_app_metadata
from utils.uuid_flags_utils import generate_and_save_flags

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
    def __init__(
        self,
        app_name: str,
        config: RunnerConfig,
        mode: str = "custom",
    ):
        self.app_name = Path(app_name).name
        self.config = config
        self.mode = mode
        self.project_root = project_root
        self.app_dir = self.project_root / "apps" / self.app_name
        self.agent_dir = self.project_root / "agent"
        self.cmd = CommandExecutor()
        self.emulator = None
        self.probe_results = {}

        log_banner("MobileCybench Runner Started", width=80)
        logger.info(f"App: {app_name}")
        logger.info(f"Configuration: {config.model_dump_json(indent=2)}")
        logger.info(f"Agent Type: {mode.capitalize()}")
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

        # Generate random flags for this test run
        logger.info("Generating random flags for this test run...")
        try:
            container_names = self.metadata.get("container_names", [])
            logger.info(f"Found containers: {container_names}")

            generate_and_save_flags(str(self.project_root), container_names)
            logger.info("✓ Random flags generated successfully")
        except Exception as e:
            self._exit_with_error(f"Failed to generate random flags: {e}")

        # Check for required scripts
        required_scripts = ["setup.sh"]

        if self.config.build_type == "source":
            required_scripts.append("setup_app_source.sh")
        elif (
            self.config.build_type == "skip-apk"
            or self.config.build_type == "download-apk"
        ):
            # Check if either setup_app_source.sh exists or download_link is in metadata
            has_setup_source = (self.app_dir / "setup_app_source.sh").exists()
            has_download_link = self.metadata.get("download_link") is not None

            if not (has_setup_source or has_download_link):
                self._exit_with_error(
                    "For build_type 'skip-apk', either setup_app_source.sh must exist or download_link must be in metadata.json"
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

        # Check for static vulnerability reports if in supervisor mode
        if self.mode == "supervisor":
            reports_root = self.app_dir / "static_vuln_reports"
            semgrep_report_path = reports_root / "semgrep" / "report.json"
            mobsf_report_path = reports_root / "mobsfscan" / "report.json"
            qark_report_path = reports_root / "qark" / "report.json"

            if not reports_root.exists() or not any(reports_root.iterdir()):
                self._exit_with_error(
                    "Supervisor mode requires static analysis outputs under "
                    f"{reports_root}. Directory is missing or empty.\n"
                    "Generate at least Semgrep (and optionally MobSF/QARK) reports before running."
                )

            # Semgrep should be present; warn if missing
            if not semgrep_report_path.exists():
                logger.warning(
                    "Semgrep report not found at %s; supervisor agents will proceed without it.",
                    semgrep_report_path,
                )
            else:
                try:
                    with open(semgrep_report_path, "r") as f:
                        json.load(f)
                    logger.info(
                        "✓ Found and validated Semgrep report for supervisor mode"
                    )
                except json.JSONDecodeError as e:
                    logger.warning(
                        "Semgrep report exists but is not valid JSON (%s); rerun Semgrep to regenerate.",
                        e,
                    )

            # MobSFScan and QARK are optional but recommended; validate if present
            for tool_name, report_path in [
                ("MobSFScan", mobsf_report_path),
                ("QARK", qark_report_path),
            ]:
                if report_path.exists():
                    try:
                        with open(report_path, "r") as f:
                            json.load(f)
                        logger.info("✓ Found %s report at %s", tool_name, report_path)
                    except json.JSONDecodeError:
                        logger.warning(
                            "%s report at %s is not valid JSON; rerun the scan to regenerate.",
                            tool_name,
                            report_path,
                        )
                else:
                    logger.warning(
                        "%s report not found at %s; continuing without it.",
                        tool_name,
                        report_path,
                    )

        logger.info("Input validation passed")

    def setup_app_apk(self):
        """APK Handling - Download, Build, or Skip"""
        if self.config.build_type == "skip-apk":
            log_banner("SKIPPING APK HANDLING STEP")
        elif self.config.build_type == "download-apk":
            log_banner("FETCHING APK USING APKLINK")
            try:
                setup_script = self.project_root / "setup_app_apklink.py"
                self.cmd.run_with_progress(
                    f"python3 {setup_script} {self.app_name}",
                    timeout=BUILD_COMMAND_TIMEOUT,
                    message="Downloading APK",
                    cwd=self.project_root,
                )
            except subprocess.CalledProcessError as e:
                self._exit_with_error(
                    f"Failed to setup app APK with setup_app_apklink.py: {e}"
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

        # In the future, once APKs uploaded to GitHub Releases include the honeypot activity,
        # we only need to inject when building from source
        log_banner("REPACKAGING APK WITH HONEYPOT ACTIVITY INJECTION")
        try:
            self.cmd.run_with_progress(
                f"bash ../../utils/repackage_apk.sh apk/{self.app_name}.apk",
                timeout=BUILD_COMMAND_TIMEOUT,
                message="Repackaging APK",
                cwd=self.app_dir,
            )
        except subprocess.CalledProcessError as e:
            self._exit_with_error(f"Failed to repackage APK with repackage_apk.sh: {e}")

        # ensures emulator is fully booted and ready
        try:
            self.emulator.wait_until_ready(timeout=EMULATOR_BOOT_TIMEOUT_SECONDS)
            logger.info("Emulator booted successfully")
        except Exception as e:
            self._exit_with_error(f"Failed to wait for emulator to finish booting: {e}")

        if not self.emulator.check_status():
            self._exit_with_error("Emulator status check failed")
        logger.info("Emulator status verified")

    def install_app_and_setup_backend(self):
        """Setup app backend and install APK"""
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

    def setup_agent_environment(self):
        """Configure agent environment and start services"""
        log_banner("SETTING UP AGENT ENVIRONMENT")

        if not self.config.dry_run:
            self._setup_env_file()
        self._create_docker_network()

        # Setup agent kali environment with appropriate image
        logger.info("Setting up agent Kali environment...")

        # Select image based on agent type
        if self.mode == "codex":
            image_name = self.config.codex_agent_image or "cybench/mobilecybench:codex"
            logger.info(f"Using Codex agent image: {image_name}")
        else:
            image_name = self.config.agent_image
            logger.info(f"Using custom agent image: {image_name}")
        agent_env = AgentEnvironment(
            app_dir=self.app_dir,
            docker_networks=["shared_net"],
            image_name=image_name,
            env={"ANDROID_ADB_SERVER_PORT": "5037"},
            commit_id=self.metadata.get("commit_version"),
            mode=self.mode,
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

    def _validate_mcp_server(self, base_url=None):
        """Validate MCP server is functional by testing command execution"""
        logger.info("Validating MCP server with 'ls' command...")

        mcp_executor = MCPToolExecutor(ngrok_base_url=base_url)
        result = mcp_executor.call_tool("execute_command", "ls /app")

        if "codebase" not in str(result):
            self._exit_with_error(
                f"MCP server validation failed: 'codebase' directory not found - response: {result}"
            )

        logger.info("✓ MCP server validation passed: 'codebase' directory found")

    def _start_containers(self):
        """Start the containerized environment."""
        logger.info("Starting containerized environment...")

        # Build environment variables
        env = os.environ.copy()

        if self.mode == "codex":
            env.update(
                {
                    "APP_NAME": self.app_name,
                    "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
                    "AGENT_TYPE": "codex",
                    "MCP_COMMAND": "python3 mcp_server.py",  # Skip ngrok for codex
                }
            )
            cmd = f"docker compose -f {self.agent_dir / 'docker-compose.yml'} up -d"
            cwd = self.project_root
        else:
            env["AGENT_TYPE"] = self.mode
            cmd = "docker compose up -d --wait"
            cwd = self.agent_dir

        logger.info("Starting containers with docker compose...")

        # Execute docker compose
        try:
            result = self.cmd.run(cmd, cwd=cwd, env=env)
            logger.info("✓ Containers started successfully")
            if result.stdout:
                logger.debug(f"Docker compose output: {result.stdout}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to start containers: {e}")
            if self.mode == "codex":
                raise
            else:
                self._exit_with_error("Failed to start containers")

        # Container verification
        logger.info("Waiting for MCP server to initialize...")
        time.sleep(5)

        # Validate MCP server functionality
        # For codex mode, use localhost directly instead of ngrok
        mcp_base_url = "http://localhost:8000" if self.mode == "codex" else None
        self._validate_mcp_server(base_url=mcp_base_url)

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

    def run_interactive_shell(self):
        """Run interactive shell for manual command execution (dry-run mode)"""
        log_banner("RUNNING INTERACTIVE SHELL (DRY-RUN MODE)")

        logger.info("Starting interactive shell for manual command execution...")
        logger.info("You can now execute commands in the kali container.")
        logger.info("Type 'exit' or 'quit' to stop the interactive shell.")
        logger.info("Type 'help' for available commands.")
        print()

        try:
            mcp_executor = MCPToolExecutor()

            # List available tools
            logger.info("Checking available tools...")
            tools = mcp_executor.list_tools()

            print("=" * 80)
            print("DRY-RUN MODE: Interactive Shell")
            print("=" * 80)
            print(f"App: {self.app_name}")
            print("Environment is fully set up (emulator, app servers, kali container)")
            print("You can now manually execute commands to test the environment.")
            print()
            print("Available commands:")
            print("  - Any shell command will be executed in the kali container")
            print("  - 'exit' or 'quit' to exit the shell")
            print("  - 'help' for this help message")
            print("  - 'tools' to list available MCP tools")
            print("=" * 80)
            print()

            command_count = 0
            while True:
                try:
                    # Get user input
                    user_input = input("kali> ").strip()

                    if not user_input:
                        continue

                    # Handle special commands
                    if user_input.lower() in ["exit", "quit"]:
                        print("Exiting interactive shell...")
                        break
                    elif user_input.lower() == "help":
                        print("Available commands:")
                        print(
                            "  - Any shell command will be executed in the kali container"
                        )
                        print("  - 'exit' or 'quit' to exit the shell")
                        print("  - 'help' for this help message")
                        print("  - 'tools' to list available MCP tools")
                        continue
                    elif user_input.lower() == "tools":
                        tools = mcp_executor.list_tools()
                        if tools and not isinstance(tools, dict):
                            print(f"Available tools ({len(tools)}):")
                            for tool in tools:
                                print(
                                    f"  - {tool.get('name', 'unknown')}: {tool.get('description', 'No description')}"
                                )
                        else:
                            print("Could not list tools or no tools available")
                        continue

                    # Execute command via MCP
                    command_count += 1
                    logger.info(f"Executing command {command_count}: {user_input}")

                    result = mcp_executor.call_tool("execute_command", user_input)

                    # Display result
                    if "error" in result:
                        print(f"ERROR: {result['error']}")
                        logger.error(
                            f"Command {command_count} failed: {result['error']}"
                        )
                    elif "result" in result and "structuredContent" in result["result"]:
                        structured = result["result"]["structuredContent"]
                        if "response" in structured:
                            print(structured["response"])
                        else:
                            print(result)
                    else:
                        print(result)

                except KeyboardInterrupt:
                    print("\nUse 'exit' or 'quit' to exit the shell")
                    continue
                except EOFError:
                    print("\nExiting interactive shell...")
                    break
                except Exception as e:
                    print(f"Error: {e}")
                    logger.error(f"Error in interactive shell: {e}")

            log_banner("INTERACTIVE SHELL SESSION COMPLETED")
            logger.info(f"Total commands executed: {command_count}")

            return {
                "status": "completed",
                "commands_executed": command_count,
                "log_file": None,
            }

        except Exception as e:
            logger.error(f"Failed to run interactive shell: {e}")
            return {
                "status": f"error: {str(e)}",
                "commands_executed": 0,
                "log_file": None,
            }

    def run_agent(self):
        """Run the agent - custom, codex, or supervisor based on mode"""
        agent_type = f"{self.mode.upper()} AGENT"
        log_banner(f"RUNNING {agent_type}")

        # If in dry-run mode, use interactive shell instead
        if self.config.dry_run:
            return self.run_interactive_shell()

        logger.info(f"Starting {agent_type.lower()} execution...")

        try:
            if self.mode == "supervisor":
                from agent.hierarchical_agent import create_and_run_supervisor_system

                logger.info("Initializing supervisor agent system...")
                logger.info("Starting supervisor agent execution...")

                result = create_and_run_supervisor_system(
                    model=self.config.model,
                    max_iterations=self.config.max_iterations,
                    allowed_tools=self.config.allowed_tools,
                )

                log_banner("SUPERVISOR AGENT EXECUTION RESULTS")
                logger.info(f"Status: {result.get('status', 'Unknown')}")
                logger.info(f"Turns: {result.get('turns', 0)}")

                return result

            elif self.mode == "codex":
                # Import and use CodexAgent
                from agent.codex_agent import CodexAgent

                logger.info("Initializing codex agent...")
                logger.info("Creating CodexAgent instance")

                # For codex mode, use localhost MCP server instead of ngrok
                from utils.mcp_utils import get_mcp_server_config

                mcp_config = get_mcp_server_config(
                    ngrok_base_url="http://localhost:8000",
                    allowed_tools=self.config.allowed_tools,
                    check_reachability=False,
                )

                agent = CodexAgent(
                    max_conversation_turns=self.config.max_iterations,
                    screenshot_enabled=self.config.screenshot_mode,
                    app_name=self.app_name,
                    app_server=getattr(self, "metadata", {}).get("app_server", None),
                    dry_run=self.config.dry_run,
                    mcp_config=mcp_config,
                    package_name=self.metadata.get("package_name"),
                    username=self.metadata.get("username"),
                    password=self.metadata.get("password"),
                )
            else:
                # Import and use CustomAgent
                from agent.custom_agent import CustomAgent

                # Create agent instance with dry_run mode for infrastructure testing
                # Set dry_run=False for actual AI execution
                logger.info("Initializing custom agent...")
                logger.info("Creating CustomAgent instance")

                agent = CustomAgent(
                    model=self.config.model,
                    max_iterations=self.config.max_iterations,
                    max_model_response_tokens=self.config.max_model_response_tokens,
                    max_kali_message_tokens=self.config.max_kali_message_tokens,
                    max_context_length=self.config.max_context_length,
                    screenshot_enabled=self.config.screenshot_mode,
                    app_name=self.app_name,
                    app_server=getattr(self, "metadata", {}).get("app_server", None),
                    # TODO - create proper dry run mode
                    # https://github.com/bountybench/mobilecybench/issues/322
                    dry_run=self.config.dry_run,
                    system_prompt=self.config.custom_system_prompt,
                    package_name=self.metadata.get("package_name"),
                    username=self.metadata.get("username"),
                    password=self.metadata.get("password"),
                )

            # This can take a while for actual LLM calls
            # (Skip for supervisor mode as it's already run above)
            if self.mode != "supervisor":
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
            logger.error(f"Failed to run agent: {e}")
            import traceback

            logger.error(f"Traceback: {traceback.format_exc()}")
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
            command = f"{command} {shlex.quote(str(log_path))}"
            logger.info(f"Passing log file to probe checks: {log_path}")
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
        scores_dict = None
        if scores_file.exists():
            try:
                with open(scores_file, "r") as f:
                    scores_dict = json.load(f)
                logger.info(f"Scores found: {json.dumps(scores_dict, indent=2)}")

            except Exception as e:
                logger.error(f"Error reading scores.json: {e}")
                scores_dict = None
        else:
            logger.info("No scores.json file found")

        return scores_dict

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

    def _run_cleanup(self):
        """Run cleanup script for the app"""
        cleanup_script = self.app_dir / "cleanup.sh"

        if not cleanup_script.exists():
            self._exit_with_error(
                f"Required cleanup script not found: {cleanup_script}"
            )

        try:
            self.cmd.run_with_progress(
                "bash ./cleanup.sh",
                timeout=BUILD_COMMAND_TIMEOUT,
                message="Running cleanup script",
                cwd=self.app_dir,
            )
        except subprocess.CalledProcessError as e:
            self._exit_with_error(f"Failed to run cleanup script: {e}")

    def _check_and_save_agent_exploit(self):
        """Ensure exploit.sh exists, log it, and copy the entire exploit_files directory to host."""
        logger.info(
            "Checking for agent-generated exploit.sh and exploit_files directory..."
        )
        exploit_path = "/app/exploit_files/exploit.sh"

        try:
            check_result = subprocess.run(
                ["docker", "exec", "kali-container", "test", "-f", exploit_path],
                capture_output=True,
                text=True,
            )

            if check_result.returncode != 0:
                logger.info(
                    "No exploit.sh file found - agent did not create an exploit script"
                )
                return False

            logger.info("Found exploit.sh in Kali container, reading contents...")
            read_result = subprocess.run(
                ["docker", "exec", "kali-container", "cat", exploit_path],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if read_result.returncode == 0:
                logger.info(f"exploit.sh contents:\n{read_result.stdout}")
            else:
                logger.warning(f"Failed to read exploit.sh: {read_result.stderr}")

            # Copy entire exploit_files directory to host (includes supporting files)
            host_logs_dir = logger_manager.get_logs_dir()
            host_exploit_dir = host_logs_dir / "exploit_files"
            host_exploit_dir.mkdir(parents=True, exist_ok=True)

            copy_result = subprocess.run(
                [
                    "docker",
                    "cp",
                    "kali-container:/app/exploit_files/.",
                    str(host_exploit_dir),
                ],
                capture_output=True,
                text=True,
            )
            if copy_result.returncode != 0:
                logger.warning(
                    "Failed to copy exploit_files directory from container: %s",
                    copy_result.stderr,
                )
            else:
                logger.info(
                    "Copied exploit_files directory from container to %s",
                    host_exploit_dir,
                )

            return True
        except Exception as e:
            logger.warning(f"Error checking/copying exploit artifacts: {e}")
            return False

    def _run_agent_exploit(self) -> Path:
        """Run the agent-generated exploit script and log output.

        Returns:
            Path to the exploit log file.
        """
        logger.info("Running agent exploit script...")

        # Path to exploit script in container
        exploit_script_path = "/app/exploit_files/exploit.sh"

        # Create exploit log file path
        logs_dir = logger_manager.get_logs_dir()
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        exploit_log_path = logs_dir / f"exploit_execution_{timestamp}.log"

        try:
            # Step 1: Dump the exploit script contents
            logger.info("Reading exploit script contents...")
            cat_result = subprocess.run(
                ["docker", "exec", "kali-container", "cat", exploit_script_path],
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Step 2: Log exploit script contents (to both logger and file)
            script_contents = cat_result.stdout
            logger.info("=" * 80)
            logger.info("EXPLOIT SCRIPT CONTENTS")
            logger.info("=" * 80)
            logger.info(script_contents)
            logger.info("=" * 80)

            # Write to log file
            with open(exploit_log_path, "w") as log_file:
                log_file.write("=" * 80 + "\n")
                log_file.write("EXPLOIT SCRIPT CONTENTS\n")
                log_file.write("=" * 80 + "\n")
                log_file.write(script_contents)
                log_file.write("\n" + "=" * 80 + "\n")

            # Step 3: Execute the exploit script and capture output
            logger.info("Executing exploit script...")
            exec_result = subprocess.run(
                ["docker", "exec", "kali-container", "bash", exploit_script_path],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout for exploit execution
            )

            # Step 4: Log execution output (stdout and stderr) to both logger and file
            logger.info("=" * 80)
            logger.info("EXPLOIT EXECUTION OUTPUT")
            logger.info("=" * 80)
            if exec_result.stdout:
                logger.info("STDOUT:")
                logger.info(exec_result.stdout)

            if exec_result.stderr:
                logger.info("STDERR:")
                logger.info(exec_result.stderr)

            logger.info("=" * 80)
            logger.info(f"EXIT CODE: {exec_result.returncode}")
            logger.info("=" * 80)

            logger.info(
                f"Exploit execution completed with exit code: {exec_result.returncode}"
            )

            # Append execution output to log file
            with open(exploit_log_path, "a") as log_file:
                log_file.write("\n" + "=" * 80 + "\n")
                log_file.write("EXPLOIT EXECUTION OUTPUT\n")
                log_file.write("=" * 80 + "\n")
                if exec_result.stdout:
                    log_file.write("STDOUT:\n")
                    log_file.write(exec_result.stdout)
                    log_file.write("\n")
                if exec_result.stderr:
                    log_file.write("STDERR:\n")
                    log_file.write(exec_result.stderr)
                    log_file.write("\n")
                log_file.write("=" * 80 + "\n")
                log_file.write(f"EXIT CODE: {exec_result.returncode}\n")
                log_file.write("=" * 80 + "\n")

            return exploit_log_path

        except subprocess.TimeoutExpired as e:
            logger.error(f"Exploit execution timed out: {e}")
            # Write timeout error to log file (create file if it doesn't exist)
            try:
                mode = "a" if exploit_log_path.exists() else "w"
                with open(exploit_log_path, mode) as log_file:
                    if mode == "w":
                        # If file didn't exist, write header first
                        log_file.write("=" * 80 + "\n")
                        log_file.write("EXPLOIT EXECUTION LOG\n")
                        log_file.write("=" * 80 + "\n")
                    log_file.write("\n" + "=" * 80 + "\n")
                    log_file.write("EXPLOIT EXECUTION TIMED OUT\n")
                    log_file.write("=" * 80 + "\n")
                    log_file.write(f"Error: {e}\n")
                    log_file.write("Command timed out after 300 seconds\n")
                    log_file.write("=" * 80 + "\n")
            except Exception:
                pass  # If file writing fails, at least return the path
            return exploit_log_path

        except Exception as e:
            logger.error(f"Failed to run agent exploit: {e}")
            # Write error to log file (create file if it doesn't exist)
            try:
                mode = "a" if exploit_log_path.exists() else "w"
                with open(exploit_log_path, mode) as log_file:
                    if mode == "w":
                        # If file didn't exist, write header first
                        log_file.write("=" * 80 + "\n")
                        log_file.write("EXPLOIT EXECUTION LOG\n")
                        log_file.write("=" * 80 + "\n")
                    log_file.write("\n" + "=" * 80 + "\n")
                    log_file.write("EXPLOIT EXECUTION FAILED\n")
                    log_file.write("=" * 80 + "\n")
                    log_file.write(f"Error: {e}\n")
                    log_file.write("=" * 80 + "\n")
            except Exception:
                pass  # If file writing fails, at least return the path
            return exploit_log_path

    def run(self):
        try:
            self.validate_input()

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

                self.setup_app_apk()
                self.install_app_and_setup_backend()
                dummy_log_path = Path(DUMMY_LOG_FILENAME)
                if not dummy_log_path.exists():
                    dummy_log_path.touch()
                self.probe_results["pre_agent_run"] = self.run_probes_checks(
                    log_file_path=dummy_log_path
                )

                self.setup_agent_environment()
                self.run_agent()

                agent_log_filename = logger_manager.get_agent_log_file_name()
                log_path = Path(agent_log_filename)
                logger.info(f"Agent log file path: {log_path}")

                self.probe_results["post_agent_run"] = self.run_probes_checks(
                    log_file_path=log_path
                )
                log_banner("Restarting services, running agent exploit")

            exploit_exists = self._check_and_save_agent_exploit()
            if not exploit_exists:
                logger.info(
                    "No Agent Exploit Found - skipping exploit execution pipeline"
                )
            else:
                with EmulatorManager(
                    docker_mode=self.config.docker_mode,
                    project_root=self.project_root,
                    sdk_version=sdk_version,
                    app_name=self.app_name,
                ) as emulator:
                    self.emulator = emulator
                    self.emulator.start_in_background()
                    logger.info("New emulator starting . . .")
                    self._run_cleanup()
                    self.setup_app_apk()
                    self.install_app_and_setup_backend()
                    dummy_log_path = Path(DUMMY_LOG_FILENAME)
                    if not dummy_log_path.exists():
                        dummy_log_path.touch()
                    self.probe_results["pre_agent_exploit"] = self.run_probes_checks(
                        log_file_path=dummy_log_path
                    )
                    self._run_agent_exploit()
                    self.probe_results["post_agent_exploit"] = self.run_probes_checks(
                        log_file_path=dummy_log_path
                    )
                    log_banner("Agent Exploit done")

        except KeyboardInterrupt:
            logger.info("Runner interrupted by user")
            return 1
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return 1
        finally:
            log_banner("PROBE RESULTS SUMMARY")
            if self.probe_results:
                logger.info(
                    f"Probe results: {json.dumps(self.probe_results, indent=2)}"
                )
            else:
                logger.info("No probe results collected")

            # Clean up agent_codebase to prevent state from leaking across runs
            if hasattr(self, "agent_env") and self.agent_env is not None:
                log_banner("CLEANING UP AGENT CODEBASE")
                try:
                    # Save the state (git diff) for debugging/analysis
                    diff = self.agent_env.save_agent_codebase_state()
                    if diff:
                        logger.info(
                            "Agent made changes to codebase - diff has been captured"
                        )
                        logger.info("=" * 80)
                        logger.info("AGENT CODEBASE DIFF START")
                        logger.info("=" * 80)
                        # Log diff line by line to preserve formatting
                        for line in diff.splitlines():
                            logger.info(line)
                        logger.info("=" * 80)
                        logger.info("AGENT CODEBASE DIFF END")
                        logger.info("=" * 80)

                    # Reset agent_codebase to original state
                    self.agent_env.delete_agent_codebase()
                    logger.info("Agent codebase cleaned up successfully")
                except Exception as e:
                    logger.error(f"Failed to cleanup agent_codebase: {e}")

            # TODO: Add cleanup for app cleanup.sh, Kali container, and MCP server
            # Should run docker compose down in agent_dir and cleanup.sh in app_dir


def main():
    # Start timing the experiment
    time_tracker.start_experiment()

    try:
        parser = argparse.ArgumentParser(
            description="MobileCybench Runner - Orchestrates AI-driven mobile app security testing"
        )

        # Add agent_type selection
        parser.add_argument(
            "--agent-type",
            choices=["custom", "codex", "supervisor"],
            default="custom",
            help="Agent type to use: 'custom' (OpenAI API), 'codex' (Codex CLI), or 'supervisor' (hierarchical multi-agent). Default: custom.",
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

        # Update experiment with app name
        time_tracker._app_name = args.app_name

        # Load configuration from file
        # If relative path, make it relative to the script directory
        config_file = args.config_file
        if not os.path.isabs(config_file):
            config_path = project_root / config_file
        else:
            config_path = Path(config_file)

        config = RunnerConfig.from_file(config_path)

        # Create and run the runner
        runner = MobileCybenchRunner(args.app_name, config, mode=args.agent_type)
        result = runner.run()

        return result

    except Exception as e:
        logger.error(f"Failed to run experiment: {e}")
        return 1
    finally:
        # Always end timing and log summary, regardless of success/failure
        time_tracker.end_experiment()
        try:
            time_tracker.log_summary(logger)

            # Save structured JSON output
            logs_dir = logger_manager.get_logs_dir()
            json_path = logs_dir / f"timings_{time_tracker._experiment_id}.json"
            time_tracker.save_json(json_path)
            logger.info(f"Timing data saved to: {json_path}")

        except Exception as e:
            logger.error(f"Failed to log timing summary: {e}")


if __name__ == "__main__":
    sys.exit(main())
