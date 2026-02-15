#!/usr/bin/env python3
"""
MobileCybench Runner - Workflow-based architecture.

This runner uses the Workflow abstraction to handle different evaluation modes:
- DiscoveryWorkflow: For discovering unknown vulnerabilities
- ExploitWorkflow: For exploiting known/synthetic vulnerabilities
"""

import argparse
import datetime
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional


def _bootstrap_runner_session_id() -> str:
    """Ensure runner process owns and exports a run/session ID."""
    run_id = os.environ.get("MOBILECYBENCH_SESSION_ID")
    if run_id:
        return run_id
    run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    os.environ["MOBILECYBENCH_SESSION_ID"] = run_id
    return run_id


_bootstrap_runner_session_id()

from models.config import RunnerConfig
from utils.git_utils import ensure_app_submodule
from utils.logger import logger, logger_manager
from utils.time_tracker import time_tracker
from workflows import DiscoveryWorkflow, ExploitWorkflow, Workflow


def run_interactive_shell(app_name: str) -> dict:
    """Run an interactive shell for manual command execution in dry-run mode."""
    from agent.tools.runtime import ToolRuntime

    tool_runtime = ToolRuntime()

    print("=" * 80)
    print("DRY-RUN MODE: Interactive Shell")
    print("=" * 80)
    print(f"App: {app_name}")
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
            user_input = input("kali> ").strip()

            if not user_input:
                continue

            if user_input.lower() in ["exit", "quit"]:
                print("Exiting interactive shell...")
                break
            elif user_input.lower() == "help":
                print("Available commands:")
                print("  - Any shell command will be executed in the kali container")
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
                        desc = tool.get("description", "No description")[:60]
                        print(f"  - {name}: {desc}")
                continue

            command_count += 1
            result = tool_runtime.execute("execute_command", {"command": user_input})
            print(result)

        except KeyboardInterrupt:
            print("\nUse 'exit' or 'quit' to exit the shell")
        except EOFError:
            print("\nExiting interactive shell...")
            break
        except Exception as e:
            print(f"Error: {e}")

    logger.info(f"Interactive shell completed. Commands executed: {command_count}")
    return {"status": "completed", "commands_executed": command_count}


def create_workflow(
    config: RunnerConfig, app_name: str, project_root: Path
) -> Workflow:
    """
    Create the appropriate workflow based on configuration.

    Args:
        config: Runner configuration
        app_name: Name of the app to evaluate
        project_root: Root directory of the project

    Returns:
        Workflow instance (DiscoveryWorkflow or ExploitWorkflow)
    """
    app_dir = project_root / "apps" / app_name

    # Common parameters for both workflows
    common_params = {
        "app_name": app_name,
        "app_dir": app_dir,
        "model": config.model,
        "max_iterations": config.max_iterations,
        "max_model_response_tokens": config.max_model_response_tokens,
        "screenshot_mode": config.screenshot_mode,
        "build_type": config.build_type,
        "agent_image": config.agent_image,
        "project_root": project_root,
        "dry_run": config.dry_run,
        "reasoning_effort": config.reasoning_effort,
        "docker_mode": config.docker_mode,
        "emulator_mode": config.emulator_mode,
    }

    if config.workflow == "exploit":
        return ExploitWorkflow(**common_params, vuln_id=config.synthetic_vuln_id)
    else:
        return DiscoveryWorkflow(**common_params)


def _log_experiment_config(
    config: RunnerConfig, app_name: str, workflow: Workflow
) -> None:
    """Log a structured summary of the full experiment configuration.

    Combines runner config with app metadata so the full experiment log
    captures everything needed to reproduce or understand the run.
    """
    metadata = getattr(workflow, "metadata", {})

    experiment_config = {
        "app": {
            "name": app_name,
            **metadata,
        },
        "runner": config.model_dump(),
    }

    # Add exploit-specific fields
    if config.workflow == "exploit":
        experiment_config["exploit"] = {
            "vuln_id": config.synthetic_vuln_id,
        }

    logger.info(
        "Experiment configuration:\n%s",
        json.dumps(experiment_config, indent=2, default=str),
    )


def _get_available_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _start_run_scoped_bridge(
    project_root: Path, run_id: str
) -> Optional[subprocess.Popen]:
    """Start host bridge bound to this run's session ID."""
    bridge_script = project_root / "tools" / "host_bridge.py"
    if not bridge_script.exists():
        logger.warning(f"Host bridge script not found: {bridge_script}")
        return None

    env = os.environ.copy()
    bridge_port = _get_available_tcp_port()
    env["MOBILECYBENCH_SESSION_ID"] = run_id
    env["MCB_BRIDGE_PORT"] = str(bridge_port)
    env.setdefault("MCB_BRIDGE_BIND", "127.0.0.1")
    os.environ["MCB_BRIDGE_PORT"] = str(bridge_port)

    proc = subprocess.Popen(
        [sys.executable, str(bridge_script)],
        cwd=str(project_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    logger.info(
        f"Started run-scoped host bridge for run_id={run_id} on port={bridge_port}"
    )
    return proc


def _stop_run_scoped_bridge(bridge_proc: Optional[subprocess.Popen]) -> None:
    if bridge_proc and bridge_proc.poll() is None:
        bridge_proc.terminate()
        try:
            bridge_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bridge_proc.kill()
    logger.info("Stopped run-scoped host bridge")


def run(config: RunnerConfig, app_name: str, project_root: Path) -> int:
    """
    Execute the evaluation workflow.

    Args:
        config: Runner configuration
        app_name: Name of the app to evaluate
        project_root: Root directory of the project

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    workflow = create_workflow(config, app_name, project_root)
    workflow_type = (
        "ExploitWorkflow" if config.workflow == "exploit" else "DiscoveryWorkflow"
    )
    logger.info(f"Created {workflow_type} for app: {app_name}")

    # Start experiment timing with the shared session ID
    run_id = logger_manager.get_session_id()
    bridge_proc = _start_run_scoped_bridge(project_root, run_id)
    time_tracker.start_experiment(app_name, run_id=run_id)

    try:
        logger.info("Step 1/5: Validating arguments...")
        workflow.validate_arguments()
        logger.info("Arguments validated")

        ensure_app_submodule(project_root, app_name)

        # Log structured experiment configuration for observability
        _log_experiment_config(config, app_name, workflow)

        logger.info("Step 2/5: Setting up runtime environment...")
        workflow.setup_runtime_environment()
        logger.info("Runtime environment ready")

        if config.dry_run:
            logger.info("Dry run mode - launching interactive shell...")
            run_interactive_shell(app_name)
            logger.info("Interactive shell exited")
        else:
            logger.info("Step 3/5: Setting up agent...")
            workflow.setup_agent()
            logger.info("Agent configured")

            logger.info("Step 4/5: Running agent...")
            result = workflow.run_agent()
            logger.info(f"Agent completed: {result.get('status', 'unknown')}")

            # Save agent artifacts (exploit_files) before cleanup
            workflow.save_artifacts(logger_manager.get_logs_dir())

            logger.info("Step 5/5: Evaluating results...")
            scores = workflow.evaluate()
            logger.info(f"Evaluation complete: {scores}")

        return 0

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return 1
    finally:
        # Finalize experiment timing
        time_tracker.end_experiment()
        try:
            time_tracker.save_json(
                logger_manager.get_logs_dir() / f"timing_{logger_manager.get_session_id()}.json"
            )
        except Exception as e:
            logger.warning(f"Failed to save timing JSON: {e}")
        time_tracker.log_summary(logger)

        # Always cleanup resources (emulator, containers, restore APKs)
        logger.info("Cleaning up resources...")
        try:
            workflow.cleanup()
        except Exception as cleanup_error:
            logger.warning(f"Cleanup error: {cleanup_error}")
        finally:
            _stop_run_scoped_bridge(bridge_proc)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="MobileCybench Runner")
    parser.add_argument("app_name", help="Name of the app to evaluate")
    parser.add_argument(
        "--config",
        default="runner_config.json",
        help="Path to runner config file",
    )
    args = parser.parse_args()

    # Load config
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        return 1

    with open(config_path) as f:
        config_data = json.load(f)

    config = RunnerConfig(**config_data)
    project_root = Path(__file__).parent

    exit_code = run(config, args.app_name, project_root)

    # Print error summary at the very end for better visibility
    logger_manager.print_error_summary()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
