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
from agent.tools.runtime import ToolRuntime
from models.config import RunnerConfig
from utils.command_executor import CommandExecutor
from utils.emulator_manager import EmulatorManager
from utils.logger import logger, logger_manager
from utils.run_synthetic_checks import run_synthetic_checks as _run_synthetic_checks
from utils.ssrf_utils import (
    clear_ssrf_requests,
    start_ssrf_listener,
    stop_ssrf_listener,
)
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

        try:
            git_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            git_commit = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            git_info = f"Branch: {git_branch} | Commit: {git_commit}"
        except subprocess.CalledProcessError:
            git_info = "Git info unavailable"

        log_banner("MobileCybench Runner Started", width=80)
        logger.info(git_info.center(80))
        logger.info("=" * 80)
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

        # TODO - check api key based on model, potentially want to refactor this into model class
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

    def _validate_input(self):
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
        if self.config.build_type == "skip-apk":
            # Check if any .apk file exists in app_dir/apk/
            apk_dir = self.app_dir / "apk"
            apk_exists = any(apk_dir.glob("*.apk")) if apk_dir.exists() else False
            if not apk_exists:
                self._exit_with_error(
                    f"For build_type 'skip-apk', an APK file must exist in {apk_dir}"
                )

        elif self.config.build_type == "source":
            # Check for setup_app_source.sh
            if not (self.app_dir / "setup_app_source.sh").exists():
                self._exit_with_error(
                    "For build_type 'source', setup_app_source.sh must exist in the app directory"
                )

        elif self.config.build_type == "download-apk":
            # Check for download_link in metadata
            if not self.metadata.get("download_link"):
                self._exit_with_error(
                    "For build_type 'download-apk', 'download_link' must be present in metadata.json"
                )

        else:
            self._exit_with_error(
                f"Unsupported Build Type Detected: {self.config.build_type}"
            )

        # Synthetic vulnerability workflow constraints
        if self.config.synthetic_vuln:
            if self.config.build_type != "source":
                self._exit_with_error(
                    "Synthetic vulnerability mode requires build_type 'source'."
                )
            synth_root = self.app_dir / "synthetic_vulnerabilities"
            vuln_dirs = sorted(
                p
                for p in synth_root.glob("*")
                if p.is_dir() and not p.name.startswith(".")
            )
            patch_paths = [p / "vulnerability.patch" for p in vuln_dirs]
            patch_paths = [p for p in patch_paths if p.exists()]
            if not patch_paths:
                self._exit_with_error(
                    f"No synthetic vulnerability patches found under {synth_root}/<vuln_id>/vulnerability.patch"
                )
            self.synthetic_patch_paths = patch_paths
            self.synthetic_vuln_dirs = [p.parent for p in patch_paths]

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
                    "Semgrep report not found at %s; supervisor agents will proceed without it.\n"
                    "To generate it, run: python tools/run_semgrep_scan.py %s",
                    semgrep_report_path,
                    self.app_name,
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

    def _apply_synthetic_patch(self):
        patch_paths = getattr(self, "synthetic_patch_paths", None)
        if not patch_paths:
            return

        codebase_dir = self.app_dir / "codebase"
        if not codebase_dir.exists():
            codebase_dir = self.app_dir

        for patch_path in patch_paths:
            logger.info(f"Applying synthetic patch: {patch_path}")
            result = subprocess.run(
                ["git", "apply", str(patch_path)],
                cwd=codebase_dir,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                logger.info(f"Patch did not apply: {result.stderr.strip()}")
                logger.info(
                    "This is fine if patch is already applied or codebase is dirty"
                )
            else:
                logger.info("Patch applied successfully")

    def _setup_app_apk(self):
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

    def _install_app_and_setup_backend(self):
        """Setup app backend and install APK"""
        try:
            self.emulator.wait_until_ready(timeout=EMULATOR_BOOT_TIMEOUT_SECONDS)
            logger.info("Emulator booted successfully")
        except Exception as e:
            self._exit_with_error(f"Failed to wait for emulator to finish booting: {e}")

        if not self.emulator.check_status():
            self._exit_with_error("Emulator status check failed")
        logger.info("Emulator status verified")
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

        # Start SSRF listener for detecting SSRF attacks
        # Check if app has backend containers
        metadata = get_app_metadata(self.app_name)
        container_names = metadata.get("container_names", [])

        if container_names:
            logger.info("Starting SSRF listener...")
            try:
                ssrf_compose_dir = project_root / "evaluation" / "ssrf_listener"
                if start_ssrf_listener(ssrf_compose_dir):
                    logger.info("✓ SSRF listener started successfully")
                else:
                    logger.warning(
                        "⚠ Failed to start SSRF listener - SSRF detection may not work"
                    )
            except Exception as e:
                logger.warning(f"⚠ Failed to start SSRF listener: {e}")
        else:
            logger.info("No backend containers defined - skipping SSRF listener setup")

        logger.info("App setup completed")

    def _setup_agent_environment(self):
        """Configure agent environment and start services"""
        log_banner("SETTING UP AGENT ENVIRONMENT")

        self._create_docker_network()

        # Clear any previous SSRF requests before agent starts
        logger.info("Clearing previous SSRF requests...")
        try:
            clear_ssrf_requests()
            logger.info("✓ SSRF requests cleared")
        except Exception as e:
            logger.warning(f"⚠ Failed to clear SSRF requests: {e}")

        # Setup agent kali environment with appropriate image
        logger.info("Setting up agent Kali environment...")

        image_name = self.config.agent_image
        logger.info(f"Using agent image: {image_name}")
        # Prepare environment variables
        env_vars = {
            "ANDROID_ADB_SERVER_PORT": "5037",
            "ADB_SERVER_SOCKET": "tcp:host.docker.internal:5037",
        }

        # In codex mode, pass OPENAI_API_KEY as CODEX_API_KEY to the container
        if self.mode == "codex":
            openai_key = os.getenv("OPENAI_API_KEY")
            if openai_key:
                env_vars["CODEX_API_KEY"] = openai_key
                logger.info("Injected CODEX_API_KEY into agent container environment")
            else:
                logger.error("No OPENAI_API_KEY, exiting")
                sys.exit(1)

        agent_env = AgentEnvironment(
            app_dir=self.app_dir,
            docker_networks=["shared_net"],
            image_name=image_name,
            env=env_vars,
            commit_id=self.metadata.get("commit_version"),
            mode=self.mode,
            synthetic_vulns=["vuln_0"] if self.config.synthetic_vuln else None,
        )
        agent_env.setup()
        self.agent_env = agent_env

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

    def run_interactive_shell(self):
        log_banner("RUNNING INTERACTIVE SHELL (DRY-RUN MODE)")

        logger.info("Starting interactive shell for manual command execution...")
        logger.info("You can now execute commands in the kali container.")
        logger.info("Type 'exit' or 'quit' to stop the interactive shell.")
        logger.info("Type 'help' for available commands.")
        print()

        try:
            tool_runtime = ToolRuntime()

            # List available tools
            logger.info("Checking available tools...")
            tools = tool_runtime.get_tool_definitions()

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
            print("  - 'tools' to list available tools")
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
                        print("  - 'tools' to list available tools")
                        continue
                    elif user_input.lower() == "tools":
                        tools = tool_runtime.get_tool_definitions()
                        if tools and isinstance(tools, list):
                            print(f"Available tools ({len(tools)}):")
                            for tool in tools:
                                name = tool.get("name", "unknown")
                                desc = tool.get("description", "No description")
                                print(f"  - {name}: {desc}")
                        else:
                            print("Could not list tools or no tools available")
                        continue

                    # Execute command via Runtime
                    command_count += 1
                    logger.info(f"Executing command {command_count}: {user_input}")

                    result = tool_runtime.execute(
                        "execute_command", {"command": user_input}
                    )

                    # Display result
                    if isinstance(result, str) and result.startswith("Error"):
                        print(result)
                        logger.error(f"Command {command_count} failed: {result}")
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

    def _run_agent(self):
        """Run the agent - custom, codex, or supervisor based on mode"""
        agent_type = f"{self.mode.upper()} AGENT"
        log_banner(f"RUNNING {agent_type}")

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
                    metadata=getattr(self, "metadata", {}),
                )

                log_banner("SUPERVISOR AGENT EXECUTION RESULTS")
                logger.info(f"Status: {result.get('status', 'Unknown')}")
                logger.info(f"Turns: {result.get('turns', 0)}")

                return result

            elif self.mode == "codex":
                from agent.codex_agent import CodexAgent

                logger.info("Initializing codex agent...")
                logger.info("Creating CodexAgent instance")

                agent = CodexAgent(
                    app_name=self.app_name,
                    dry_run=self.config.dry_run,
                    app_server=getattr(self, "metadata", {}).get("app_server", None),
                    package_name=self.metadata.get("package_name"),
                    username=self.metadata.get("username"),
                    password=self.metadata.get("password"),
                )

            else:
                from agent.custom_agent import CustomAgent

                logger.info("Initializing custom agent...")
                logger.info("Creating CustomAgent instance")

                # Check if we should include SSRF instructions
                container_names = self.metadata.get("container_names", [])
                include_ssrf = bool(container_names)

                # Build additional context from custom prompt
                additional_parts = []
                if self.config.custom_system_prompt:
                    additional_parts.append(self.config.custom_system_prompt)

                agent = CustomAgent(
                    model=self.config.model,
                    max_iterations=self.config.max_iterations,
                    max_model_response_tokens=self.config.max_model_response_tokens,
                    max_kali_message_tokens=self.config.max_kali_message_tokens,
                    max_context_length=self.config.max_context_length,
                    screenshot_enabled=self.config.screenshot_mode,
                    app_name=self.app_name,
                    app_server=getattr(self, "metadata", {}).get("app_server", None),
                    dry_run=self.config.dry_run,
                    additional_context=(
                        "\n\n".join(additional_parts) if additional_parts else None
                    ),
                    package_name=self.metadata.get("package_name"),
                    reasoning_effort=self.config.reasoning_effort,
                    username=self.metadata.get("username"),
                    password=self.metadata.get("password"),
                    include_ssrf=include_ssrf,
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

            # Supervisor mode already returned above, but satisfy type checker
            return {
                "status": "error",
                "turns": 0,
                "final_message": None,
                "log_file": None,
            }

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

    def run_probes_checks(self, log_file_path: Path) -> dict:
        log_banner("RUNNING PROBE CHECKS")
        results: dict = {}

        app_relative_path = f"apps/{self.app_name}"
        command = f"bash ./run_checks.sh {shlex.quote(app_relative_path)}"

        log_path = Path(log_file_path)
        if log_path.exists() and log_path.is_file():
            command = f"{command} {shlex.quote(str(log_path))}"

        metadata = get_app_metadata(self.app_name)
        container_names = metadata.get("container_names", [])
        env = os.environ.copy()
        if not container_names:
            env["SKIP_SSRF_CHECK"] = "1"

        try:
            result = self.cmd.run(command, cwd=self.project_root, check=False, env=env)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to run probe checks: {e}")
            result = e

        if hasattr(result, "stdout") and result.stdout and result.stdout.strip():
            logger.info(result.stdout)
        if hasattr(result, "stderr") and result.stderr and result.stderr.strip():
            logger.info(result.stderr)

        return_code = getattr(result, "returncode", 1)
        logger.info(f"Probe checks completed (exit code: {return_code})")

        scores_file = self.app_dir / "scores.json"
        if scores_file.exists():
            try:
                with open(scores_file, "r") as f:
                    results["regular"] = json.load(f)
                logger.info(
                    f"Regular scores: {json.dumps(results['regular'], indent=2)}"
                )
            except Exception as e:
                logger.error(f"Error reading scores.json: {e}")

        # Run synthetic probes if enabled
        if self.config.synthetic_vuln:
            log_path_for_synthetic = log_path if log_path.is_file() else None
            synthetic_result = _run_synthetic_checks(
                self.app_dir, exploit_log=log_path_for_synthetic
            )
            results["synthetic"] = synthetic_result
            logger.info(
                f"Synthetic scores: {json.dumps(synthetic_result['scores'], indent=2)}"
            )

        return results

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

        # Stop SSRF listener
        try:
            ssrf_compose_dir = project_root / "evaluation" / "ssrf_listener"
            stop_ssrf_listener(ssrf_compose_dir)
            logger.info("SSRF listener stopped")
        except Exception as e:
            logger.warning(f"Error stopping SSRF listener: {e}")

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
                [
                    "docker",
                    "exec",
                    "kali-container",
                    "bash",
                    exploit_script_path,
                ],
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
            self._validate_input()
            if not self.config.dry_run:
                self._setup_env_file()
            if self.config.synthetic_vuln:
                self._apply_synthetic_patch()
            log_banner("SETTING UP ANDROID EMULATOR")
            sdk_version = (
                self.metadata.get("sdk") if hasattr(self, "metadata") else None
            )
            with EmulatorManager(
                docker_mode=self.config.docker_mode,
                project_root=self.project_root,
                sdk_version=sdk_version,
                app_name=self.app_name,
                rootable=True,  # Phase 1: Use google_apis (rootable) for discovery
            ) as emulator:
                self.emulator = emulator
                self.emulator.start_in_background()
                logger.info("Emulator started in the background . . .")

                self._setup_app_apk()
                self._install_app_and_setup_backend()
                dummy_log_path = Path(DUMMY_LOG_FILENAME)
                if not dummy_log_path.exists():
                    dummy_log_path.touch()
                self.probe_results["pre_agent_run"] = self.run_probes_checks(
                    log_file_path=dummy_log_path
                )

                self._setup_agent_environment()
                self._run_agent()

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
                    rootable=True,
                ) as emulator:
                    self.emulator = emulator
                    self.emulator.start_in_background()
                    logger.info("New emulator starting . . .")

                    try:
                        self.emulator.wait_until_ready(
                            timeout=EMULATOR_BOOT_TIMEOUT_SECONDS
                        )
                        logger.info("Emulator booted successfully")
                    except Exception as e:
                        self._exit_with_error(
                            f"Failed to wait for emulator to finish booting: {e}"
                        )

                    self._run_cleanup()
                    self._install_app_and_setup_backend()

                    dummy_log_path = Path(DUMMY_LOG_FILENAME)
                    if not dummy_log_path.exists():
                        dummy_log_path.touch()
                    self.probe_results["pre_agent_exploit"] = self.run_probes_checks(
                        log_file_path=dummy_log_path
                    )

                    # Capture the actual exploit log
                    # TODO: should we have an LLM agent (exploit executor / validator) here instead of just exploit.sh?
                    # the generated exploit script may not be sufficient to successfully exploit the vulnerability in one shot.
                    exploit_log_path = self._run_agent_exploit()
                    time.sleep(
                        3
                    )  # Allow exploit effects to stabilize before running probes

                    # Pass the exploit log (NOT dummy log) to probes
                    self.probe_results["post_agent_exploit"] = self.run_probes_checks(
                        log_file_path=exploit_log_path
                    )
                    log_banner("Agent Exploit done")

        except KeyboardInterrupt:
            logger.info("Runner interrupted by user")
            return 1
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return 1
        finally:
            # TODO: clean up synthetic patch automatically.

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

            # Clean up SSRF listener
            log_banner("CLEANING UP SSRF LISTENER")
            try:
                ssrf_compose_dir = project_root / "evaluation" / "ssrf_listener"
                stop_ssrf_listener(ssrf_compose_dir)
                logger.info("SSRF listener stopped and cleaned up")
            except Exception as e:
                logger.warning(f"Failed to cleanup SSRF listener: {e}")

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
