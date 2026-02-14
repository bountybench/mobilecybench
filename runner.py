#!/usr/bin/env python3
"""
MobileCybench Runner - Workflow-based architecture.

This runner uses the Workflow abstraction to handle different evaluation modes:
- DiscoveryWorkflow: For discovering unknown vulnerabilities
- ExploitWorkflow: For exploiting known/synthetic vulnerabilities
"""

import argparse
import json
import sys
from pathlib import Path

from models.config import RunnerConfig
from utils.git_utils import ensure_app_submodule
from utils.logger import logger, logger_manager
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
        "config": config,
        "project_root": project_root,
        "reasoning_effort": config.agents["custom"].reasoning_effort,
    }

    if config.environment.workflow == "exploit":
        return ExploitWorkflow(
            **common_params, vuln_id=config.environment.synthetic_vuln_id
        )
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
    if config.environment.workflow == "exploit":
        experiment_config["exploit"] = {
            "vuln_id": config.environment.synthetic_vuln_id,
        }

    logger.info(
        "Experiment configuration:\n%s",
        json.dumps(experiment_config, indent=2, default=str),
    )


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
        "ExploitWorkflow"
        if config.environment.workflow == "exploit"
        else "DiscoveryWorkflow"
    )
    logger.info(f"Created {workflow_type} for app: {app_name}")

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

        if config.environment.dry_run:
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

            # Save agent artifacts (exploit_files, codebase diff) before cleanup
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
        # Always cleanup resources (emulator, containers, restore APKs)
        logger.info("Cleaning up resources...")
        try:
            workflow.cleanup()
        except Exception as cleanup_error:
            logger.warning(f"Cleanup error: {cleanup_error}")


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
