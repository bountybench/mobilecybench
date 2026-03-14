#!/usr/bin/env python3
"""
MobileCybench Runner - Workflow-based architecture.

This runner uses the Workflow abstraction to handle different evaluation modes:
- DiscoveryWorkflow: For discovering unknown vulnerabilities
- ExploitWorkflow: For exploiting known/synthetic vulnerabilities
"""

import argparse
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Optional

from models.config import RunnerConfig
from utils.git_utils import ensure_app_submodule
from utils.logger import logger, logger_manager
from utils.run_artifacts import (
    normalize_agent_result,
    utc_now_iso,
    write_run_summary,
)  # noqa: E402
from utils.time_tracker import time_tracker  # noqa: E402
from workflows import (
    DetectionWorkflow,
    DiscoveryWorkflow,
    ExploitWorkflow,
    Workflow,
)  # noqa: E402


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


def _run_gold_exploit(workflow: "ExploitWorkflow", logs_dir: Path) -> dict:
    """Run the gold (reference) exploit instead of the LLM agent.

    Copies the known-good exploit_files from the synthetic vulnerability
    directory into the kali container, executes exploit.sh, then runs
    the full evaluation pipeline.
    """
    gold_dir = (
        workflow.app_dir
        / "synthetic_vulnerabilities"
        / workflow.vuln_id
        / "exploit_files"
    )
    if not gold_dir.exists():
        raise FileNotFoundError(f"Gold exploit directory not found: {gold_dir}")

    container = workflow.agent_env.container
    if not container:
        raise RuntimeError("Kali container not running — cannot copy exploit files")

    # Copy gold exploit files into /app/agent_exploit/ (where the
    # evaluation pipeline expects to find exploit.sh).
    logger.info(f"Copying gold exploit files from {gold_dir} into kali container...")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for f in gold_dir.iterdir():
            tar.add(str(f), arcname=f"agent_exploit/{f.name}")
    buf.seek(0)
    container.put_archive("/app", buf.getvalue())
    logger.info("Gold exploit files copied into container at /app/agent_exploit/")

    # Execute exploit.sh
    logger.info("Executing gold exploit: bash /app/agent_exploit/exploit.sh")
    exit_code, output = container.exec_run(
        "bash /app/agent_exploit/exploit.sh",
        workdir="/app",
    )
    output_text = output.decode() if isinstance(output, bytes) else str(output)
    logger.info(f"exploit.sh exit code: {exit_code}")
    logger.info(f"exploit.sh output:\n{output_text}")

    if exit_code != 0:
        logger.warning(f"Gold exploit.sh exited with non-zero code: {exit_code}")

    # Save artifacts (agent_exploit, agent_output) from the container
    workflow.save_artifacts(logs_dir)

    # Remove kali container before evaluation (matches normal flow)
    if workflow.agent_env:
        workflow.agent_env.cleanup()

    # Run evaluation
    logger.info("Evaluating gold exploit results...")
    scores = workflow.evaluate()

    # Write gold run result file
    gold_result = {
        "mode": "gold_run",
        "app": workflow.app_name,
        "vuln_id": workflow.vuln_id,
        "exploit_exit_code": exit_code,
        "exploit_output": output_text,
        "evaluation": scores,
        "score": scores.get("score") if isinstance(scores, dict) else None,
    }
    gold_result_path = logs_dir / "gold_run_result.json"
    gold_result_path.write_text(json.dumps(gold_result, indent=2))

    # Clear pass/fail banner
    score = gold_result["score"]
    logger.info("=" * 60)
    if score == 1:
        logger.info("GOLD RUN PASSED — exploit verified successfully (score=1)")
    else:
        logger.info(f"GOLD RUN FAILED — score={score}")
        logger.info(f"Evaluation details: {scores}")
    logger.info(f"Result saved to: {gold_result_path}")
    logger.info("=" * 60)

    return scores


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
    if config.workflow == "exploit":
        return ExploitWorkflow(config, app_name, project_root)
    if config.workflow == "detection":
        return DetectionWorkflow(config, app_name, project_root)
    return DiscoveryWorkflow(config, app_name, project_root)


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
    workflow_type = type(workflow).__name__
    logger.info(f"Created {workflow_type} for app: {app_name}")

    # Start experiment timing with the shared session ID
    run_id = logger_manager.get_run_id()
    logger_manager.update_latest_symlink()
    started_at = utc_now_iso()
    start_error_count = logger_manager.get_error_count()
    timing_start_idx = len(time_tracker.llm_calls)
    time_tracker.start_experiment(app_name, run_id=run_id)

    run_result: dict = normalize_agent_result(None)
    evaluation: dict = {}
    outcome = "failure"
    exit_reason = "runtime_exception"
    exit_code = 1

    try:
        logger.info("Validating arguments...")
        workflow.validate_arguments()
        logger.info("Arguments validated")

        ensure_app_submodule(project_root, app_name)

        # Log structured experiment configuration for observability
        _log_experiment_config(config, app_name, workflow)

        logger.info("Setting up runtime environment...")
        workflow.setup_runtime_environment()
        logger.info("Runtime environment ready")

        if config.gold_run:
            logger.info("Gold run mode — using reference exploit files...")
            scores = _run_gold_exploit(workflow, logger_manager.get_logs_dir())
            evaluation = scores or {}
            run_result = normalize_agent_result({"status": "gold_run_completed"})
            logger.info(f"Gold run complete: {scores}")
            outcome = "success"
            exit_reason = "gold_run_completed"
            exit_code = 0
        elif config.dry_run:
            logger.info("Dry run mode - launching interactive shell...")
            run_result = normalize_agent_result(run_interactive_shell(app_name))
            run_result["status"] = "dry_run_completed"
            logger.info("Interactive shell exited")
            outcome = "success"
            exit_reason = "dry_run_completed"
            exit_code = 0
        else:
            logger.info("Configuring agent...")
            workflow.setup_agent()
            logger.info("Agent configured")

            logger.info("Starting agent execution...")
            run_result = normalize_agent_result(workflow.run_agent())
            logger.info(
                f"Agent execution completed: {run_result.get('status', 'unknown')}"
            )

            # Save agent artifacts (agent_exploit, agent_output) while container is alive
            workflow.save_artifacts(logger_manager.get_logs_dir())

            # Kill the agent container before evaluation so verify scripts
            # cannot depend on it — matches CI behavior where the exploit
            # container is removed before verify_exploit.sh runs.
            if workflow.agent_env:
                workflow.agent_env.cleanup()

            logger.info("Evaluating results...")
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
        time_tracker.log_summary(logger)

        # Always cleanup resources (emulator, containers, restore APKs)
        logger.info("Cleaning up resources...")

        # Capture Logcat before stopping emulator
        if workflow.emulator:
            try:
                logcat_path = logger_manager.get_logs_dir() / "android_system.log"
                logger.info(f"Capturing Android Logcat to {logcat_path}...")

                # Use subprocess directly since emulator.execute_adb_command doesn't exist
                with open(logcat_path, "w") as f:
                    subprocess.run(["adb", "logcat", "-d"], stdout=f, timeout=10)
            except Exception as e:
                logger.warning(f"Failed to capture logcat: {e}")

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
            ended_at=utc_now_iso(),
            start_error_count=start_error_count,
            timing_start_idx=timing_start_idx,
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
    try:
        config = RunnerConfig.from_file(config_path)
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        return 1
    project_root = Path(__file__).parent

    # Initialize LoggerManager with config before any logging occurs
    from utils.logger import get_logger_manager

    get_logger_manager(config=config.model_dump())

    exit_code = run(config, args.app_name, project_root, config_path=config_path)

    # Print error summary at the very end for better visibility
    logger_manager.print_error_summary()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
