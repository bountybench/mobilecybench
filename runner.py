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

from models.config import RunnerConfig  # noqa: E402
from utils.git_utils import ensure_app_submodule  # noqa: E402
from utils.logger import logger, logger_manager  # noqa: E402
from utils.run_artifacts import normalize_agent_result, write_run_summary  # noqa: E402
from utils.time_tracker import time_tracker  # noqa: E402
from workflows import DiscoveryWorkflow, ExploitWorkflow, Workflow  # noqa: E402


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
        "script_timeout": config.script_timeout,
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


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def run(
    config: RunnerConfig,
    app_name: str,
    project_root: Path,
    config_path: Optional[Path] = None,
) -> int:
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
    started_at = _utc_now_iso()
    start_error_count = logger_manager.get_error_count()
    timing_start_idx = len(time_tracker.llm_calls)
    time_tracker.start_experiment(app_name, run_id=run_id)

    run_result: dict = normalize_agent_result(None)
    evaluation: dict = {}
    outcome = "failure"
    exit_reason = "runtime_exception"
    exit_code = 1
    timing_json_path: Optional[Path] = None

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
            run_result = normalize_agent_result(run_interactive_shell(app_name))
            run_result["status"] = "dry_run_completed"
            logger.info("Interactive shell exited")
            outcome = "success"
            exit_reason = "dry_run_completed"
            exit_code = 0
        else:
            logger.info("Step 3/5: Setting up agent...")
            workflow.setup_agent()
            logger.info("Agent configured")

            logger.info("Step 4/5: Running agent...")
            run_result = normalize_agent_result(workflow.run_agent())
            logger.info(f"Agent completed: {run_result.get('status', 'unknown')}")

            # Save agent artifacts (agent_exploit, agent_output) while container is alive
            workflow.save_artifacts(logger_manager.get_logs_dir())

            # Kill the agent container before evaluation so verify scripts
            # cannot depend on it — matches CI behavior where the exploit
            # container is removed before verify_exploit.sh runs.
            if workflow.agent_env:
                workflow.agent_env.cleanup()

            logger.info("Step 5/5: Evaluating results...")
            evaluation = workflow.evaluate() or {}
            logger.info(f"Evaluation complete: {evaluation}")
            outcome = "success"
            exit_reason = "completed"
            exit_code = 0

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        exit_reason = "validation_error"
        exit_code = 1
    except Exception as e:
        logger.error(f"Error: {e}")

        import traceback

        logger.error(traceback.format_exc())
        exit_reason = "runtime_exception"
        exit_code = 1
    finally:
        # Finalize experiment timing
        time_tracker.end_experiment()
        try:
            timing_json_path = (
                logger_manager.get_logs_dir()
                / f"timing_{logger_manager.get_session_id()}.json"
            )
            time_tracker.save_json(timing_json_path)
        except Exception as e:
            logger.warning(f"Failed to save timing JSON: {e}")
            timing_json_path = None
        time_tracker.log_summary(logger)

        # Always cleanup resources (emulator, containers, restore APKs)
        logger.info("Cleaning up resources...")
        try:
            workflow.cleanup()
        except Exception as cleanup_error:
            logger.warning(f"Cleanup error: {cleanup_error}")

        write_run_summary(
            project_root=project_root,
            run_id=run_id,
            app_name=app_name,
            config=config,
            config_path=config_path,
            workflow=workflow,
            run_result=run_result,
            evaluation=evaluation,
            outcome=outcome,
            exit_reason=exit_reason,
            started_at=started_at,
            ended_at=_utc_now_iso(),
            start_error_count=start_error_count,
            timing_start_idx=timing_start_idx,
            timing_json_path=timing_json_path,
        )

    return exit_code


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

    exit_code = run(config, args.app_name, project_root, config_path=config_path)

    # Print error summary at the very end for better visibility
    logger_manager.print_error_summary()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
