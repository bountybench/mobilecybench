#!/usr/bin/env python3
"""
MobileCybench Runner - Workflow-based architecture.

This runner uses the Workflow abstraction to handle different evaluation modes:
- ExploitWorkflow: For exploiting known/synthetic vulnerabilities
- RedTeamWorkflow: For red-team evaluation of app security
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
from utils.replay_run import (
    ReplayRunError,
    ReplaySource,
    load_replay_source,
    stage_replay_exploit,
)
from utils.run_artifacts import (
    normalize_agent_result,
    utc_now_iso,
    write_run_summary,
)
from utils.time_tracker import time_tracker
from workflows import (
    ExploitWorkflow,
    RedTeamWorkflow,
    Workflow,
)


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


def _run_gold_exploit(workflow: Workflow, logs_dir: Path) -> dict:
    """Run the gold (reference) exploit instead of the LLM agent.

    Copies the known-good exploit files into the kali container (so
    save_artifacts can extract them), then tears down the kali container
    and runs the normal evaluation pipeline.

    For redteam: uses task/exploit_files/ from zerodays submodule.
    For exploit: uses synthetic_vulnerabilities/{vuln_id}/exploit_files/.
    """
    attacker_model = workflow.config.attacker_model

    if workflow.config.workflow == "redteam":
        # Task dir is source of truth for gold exploit files
        gold_dir = (
            Path(__file__).resolve().parent
            / "zerodays"
            / "reports"
            / workflow.app_name
            / workflow.config.task
            / "task"
            / "exploit_files"
        )
    else:
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

    # Validate exploit layout per attack model.
    if attacker_model == "malicious_app":
        if not (gold_dir / "exploit_apk").exists():
            raise FileNotFoundError(f"exploit_apk/ not found in {gold_dir}")
    elif attacker_model == "remote_attacker":
        if not (gold_dir / "exploit.sh").exists():
            raise FileNotFoundError(f"exploit.sh not found in {gold_dir}")

    logger.info(f"Copying gold exploit files from {gold_dir} into kali container...")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", dereference=True) as tar:
        # Flatten task/exploit_files/ → agent_exploit/ in the container
        tar.add(str(gold_dir), arcname="agent_exploit", recursive=True)
        # Inject build script from template (single source of truth).
        if attacker_model == "malicious_app":
            build_script = (
                Path(__file__).resolve().parent
                / "templates"
                / "malicious_app"
                / "build_exploit_apk.sh"
            )
            if build_script.exists():
                tar.add(
                    str(build_script),
                    arcname="agent_exploit/exploit_apk/build_exploit_apk.sh",
                )
    buf.seek(0)
    container.put_archive("/app", buf)
    logger.info("Gold exploit files copied into container at /app/agent_exploit/")

    # Save artifacts (agent_exploit, agent_output) from the container,
    # then remove kali container before evaluation (matches normal flow).
    try:
        workflow.save_artifacts(logs_dir)
    finally:
        if workflow.agent_env:
            workflow.agent_env.cleanup()
            workflow.agent_env = None  # prevent double-cleanup in finally

    # Run evaluation — replays exploit.sh in a fresh container via
    # run_exploit_container.sh, then verifies on both vuln and clean APKs.
    logger.info("Evaluating gold exploit results...")
    scores = workflow.evaluate()

    # Write gold run result file
    gold_result = {
        "mode": "gold_run",
        "app": workflow.app_name,
        "vuln_id": getattr(workflow, "vuln_id", None),
        "evaluation": scores,
        "score": scores.get("score") if isinstance(scores, dict) else None,
    }
    gold_result_path = logs_dir / "gold_run_result.json"
    gold_result_path.write_text(json.dumps(gold_result, indent=2))

    score = gold_result["score"]
    if isinstance(scores, dict):
        logger.info(
            "Gold run evaluation: status=%s score=%s reason=%s",
            scores.get("status"),
            scores.get("score"),
            scores.get("reason"),
        )
    if score == 1:
        logger.info("Gold run passed: exploit verified successfully")
    else:
        logger.info(f"Gold run failed: score={score}")
    logger.info(f"Gold run result saved to: {gold_result_path}")

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
        Workflow instance (ExploitWorkflow or RedTeamWorkflow)
    """
    if config.workflow == "redteam":
        return RedTeamWorkflow(config, app_name, project_root)
    return ExploitWorkflow(config, app_name, project_root)


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
        "Run config: app=%s workflow=%s attacker_model=%s",
        app_name,
        config.workflow,
        config.attacker_model,
    )
    logger.info(
        "Runner settings: gold_run=%s replay_run=%s task=%s dry_run=%s model=%s iterations=%s",
        str(config.gold_run).lower(),
        config.replay_run,
        config.task,
        str(config.dry_run).lower(),
        config.model,
        config.max_iterations,
    )
    logger.info(
        "Access: adb=%s server_access=%s emulator=%s/%s",
        config.adb_access,
        str(config.server_access).lower(),
        config.emulator_backend,
        config.emulator_display,
    )
    logger.info(
        "App config: package=%s commit=%s",
        metadata.get("package_name"),
        metadata.get("commit_version"),
    )
    if metadata.get("app_server") or metadata.get("emulator_server"):
        logger.info(
            "App endpoints: app_server=%s emulator_server=%s",
            metadata.get("app_server"),
            metadata.get("emulator_server"),
        )
    container_names = metadata.get("container_names", [])
    if container_names:
        logger.info("App containers: %s", ", ".join(container_names))
    logger.info(
        "Experiment configuration (full):\n%s",
        json.dumps(experiment_config, indent=2, default=str),
    )


def _load_task_attacker_model(project_root: Path, app_name: str, task: str) -> str:
    """Return attacker_model from a redteam task bundle."""
    task_meta_path = (
        project_root
        / "zerodays"
        / "reports"
        / app_name
        / task
        / "task"
        / "metadata.json"
    )
    if not task_meta_path.exists():
        raise FileNotFoundError(
            f"metadata.json not found at {task_meta_path} (required for task={task})"
        )

    task_meta = json.loads(task_meta_path.read_text())
    task_attacker_model = task_meta.get("attacker_model")
    valid_models = {"malicious_app", "remote_attacker"}
    if task_attacker_model not in valid_models:
        raise ValueError(
            f"attacker_model={'missing' if task_attacker_model is None else repr(task_attacker_model)} "
            f"in {task_meta_path} (must be one of {valid_models})"
        )
    return task_attacker_model


def _log_evaluation_result(evaluation: dict) -> None:
    """Log a normalized evaluation summary when present."""
    if isinstance(evaluation, dict):
        logger.info(
            "Evaluation complete: status=%s score=%s reason=%s",
            evaluation.get("status"),
            evaluation.get("score"),
            evaluation.get("reason"),
        )
    else:
        logger.info("Evaluation complete")


def run(
    config: RunnerConfig,
    app_name: str,
    project_root: Path,
    config_path: Optional[Path] = None,
    replay_source: Optional[ReplaySource] = None,
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
    # Start experiment timing with the shared session ID
    run_id = logger_manager.get_run_id()
    logger_manager.update_latest_symlink()
    started_at = utc_now_iso()
    start_error_count = logger_manager.get_error_count()
    timing_start_idx = len(time_tracker.llm_calls)
    time_tracker.start_experiment(app_name, run_id=run_id)

    workflow = None
    run_result: dict = normalize_agent_result(None)
    evaluation: dict = {}
    outcome = "failure"
    exit_reason = "runtime_exception"
    exit_code = 1

    try:
        # Replay-run only supplies the task slug. task/metadata.json remains the
        # single source of truth for attacker_model; we reconcile against the
        # saved artifact's attacker_model to catch stale replays.
        if replay_source:
            logger.info(
                "Replay source: %s (app=%s, task=%s, attacker_model=%s)",
                replay_source.source_dir,
                replay_source.app_name,
                replay_source.task,
                replay_source.attacker_model,
            )
            config.task = replay_source.task

        if config.task:
            task_attacker_model = _load_task_attacker_model(
                project_root, app_name, config.task
            )
            if replay_source and task_attacker_model != replay_source.attacker_model:
                raise ValueError(
                    f"Replay artifact was built for attacker_model="
                    f"{replay_source.attacker_model!r}, but task {config.task!r} now "
                    f"declares attacker_model={task_attacker_model!r}."
                )
            if task_attacker_model != config.attacker_model:
                logger.info(
                    "Task metadata overrides attacker_model: %s -> %s",
                    config.attacker_model,
                    task_attacker_model,
                )
                config.attacker_model = task_attacker_model

        workflow = create_workflow(config, app_name, project_root)
        workflow_type = type(workflow).__name__
        logger.info(f"Created {workflow_type} for app: {app_name}")

        logger.info("Validating arguments...")
        workflow.validate_arguments()
        logger.info("Arguments validated")

        ensure_app_submodule(project_root, app_name)

        # Log structured experiment configuration for observability
        _log_experiment_config(config, app_name, workflow)

        if replay_source:
            staged = stage_replay_exploit(
                replay_source,
                logs_dir=logger_manager.get_logs_dir(),
                project_root=project_root,
            )
            logger.info("Replay exploit staged into %s", staged)

        logger.info("Setting up runtime environment...")
        workflow.setup_runtime_environment()
        logger.info("Runtime environment ready")

        if config.gold_run:
            logger.info("Gold run mode — using reference exploit files...")
            scores = _run_gold_exploit(workflow, logger_manager.get_logs_dir())
            evaluation = scores or {}
            run_result = normalize_agent_result({"status": "gold_run_completed"})
            gold_score = scores.get("score") if isinstance(scores, dict) else None
            outcome = "success" if gold_score == 1 else "failure"
            exit_reason = "gold_run_completed"
            exit_code = 0 if gold_score == 1 else 1
        elif config.dry_run:
            logger.info("Dry run mode - launching interactive shell...")
            run_result = normalize_agent_result(run_interactive_shell(app_name))
            run_result["status"] = "dry_run_completed"
            logger.info("Interactive shell exited")
            outcome = "success"
            exit_reason = "dry_run_completed"
            exit_code = 0
        elif replay_source:
            logger.info("Replay-run mode — evaluating reused exploit artifact...")
            evaluation = workflow.evaluate() or {}
            _log_evaluation_result(evaluation)
            run_result = normalize_agent_result({"status": "replay_run_completed"})
            replay_score = (
                evaluation.get("score") if isinstance(evaluation, dict) else None
            )
            outcome = "success" if replay_score == 1 else "failure"
            exit_reason = "replay_run_completed"
            exit_code = 0 if replay_score == 1 else 1
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
                workflow.agent_env = None

            logger.info("Evaluating results...")
            evaluation = workflow.evaluate() or {}
            _log_evaluation_result(evaluation)

            # Derive outcome from agent_status and evaluation rather than
            # unconditionally reporting success.
            agent_status = run_result.get("status", "unknown")
            eval_score = (
                evaluation.get("score") if isinstance(evaluation, dict) else None
            )

            if agent_status in ("timeout", "error"):
                outcome = "failure"
                exit_reason = agent_status
                exit_code = 1
            elif eval_score == 1:
                outcome = "success"
                exit_reason = "completed"
                exit_code = 0
            elif eval_score is not None:
                # Evaluation ran but the exploit did not succeed
                outcome = "failure"
                exit_reason = "completed"
                exit_code = 1
            else:
                # No evaluation score (non-exploit workflow or eval skipped)
                outcome = "success"
                exit_reason = "completed"
                exit_code = 0

    except (ValueError, ReplayRunError) as e:
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
        if workflow and workflow.emulator:
            try:
                logcat_path = logger_manager.get_logs_dir() / "android_system.log"
                logger.info(f"Capturing Android Logcat to {logcat_path}...")

                # Use subprocess directly since emulator.execute_adb_command doesn't exist
                with open(logcat_path, "w") as f:
                    subprocess.run(["adb", "logcat", "-d"], stdout=f, timeout=10)
            except Exception as e:
                logger.warning(f"Failed to capture logcat: {e}")

        if workflow:
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
    parser.add_argument(
        "app_name",
        nargs="?",
        help="Name of the app to evaluate (optional when --replay-run is used)",
    )
    parser.add_argument(
        "--config",
        default="runner_config.json",
        help="Path to runner config file",
    )
    parser.add_argument(
        "--replay-run",
        help="Replay a prior redteam experiment from logs/experiment_<uuid>",
    )
    args = parser.parse_args()

    # Load config
    config_path = Path(args.config)
    try:
        config = RunnerConfig.from_file(
            config_path,
            overrides={"replay_run": args.replay_run} if args.replay_run else None,
        )
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        return 1
    if not args.app_name and not config.replay_run:
        parser.error("app_name is required unless --replay-run is provided")

    project_root = Path(__file__).parent

    # Initialize LoggerManager with config before any logging occurs
    from utils.logger import get_logger_manager

    get_logger_manager(config=config.model_dump())

    replay_source = None
    app_name = args.app_name
    if config.replay_run:
        try:
            replay_source = load_replay_source(config.replay_run, project_root)
        except ReplayRunError as e:
            logger.error(str(e))
            logger_manager.print_error_summary()
            return 1
        app_name = app_name or replay_source.app_name

    exit_code = run(
        config,
        app_name,
        project_root,
        config_path=config_path,
        replay_source=replay_source,
    )

    # Print error summary at the very end for better visibility
    logger_manager.print_error_summary()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
