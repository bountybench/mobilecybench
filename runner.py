#!/usr/bin/env python3
"""
MobileCybench Runner - Workflow-based architecture.

This runner uses the Workflow abstraction to handle different evaluation modes:
- RedTeamWorkflow: For red-team evaluation of app security
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from batch_runner import config_file_has_batch, load_batch_config_parts
from batch_runner import run_batch as _run_batch
from models.config import BatchRunnerConfig, RunnerConfig
from utils.exploit_source import (
    ExploitSourceError,
    overlay_canonical_build_script,
    resolve_gold_source,
    stage_exploit_source,
)
from utils.git_utils import ensure_app_submodule, ensure_zerodays_submodule
from utils.logger import logger, logger_manager
from utils.run_artifacts import (
    normalize_agent_result,
    utc_now_iso,
    write_run_summary,
)
from utils.time_tracker import time_tracker
from workflows import (
    RedTeamWorkflow,
    Workflow,
)


def run_interactive_shell(app_name: str) -> dict:
    """Run an interactive shell for manual command execution in dry-run mode."""
    from agent.custom.tools.runtime import ToolRuntime

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
        Workflow instance.
    """
    return RedTeamWorkflow(config, app_name, project_root)


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

    logger.info(
        "Run config: app=%s workflow=%s attacker_model=%s",
        app_name,
        config.workflow,
        config.attacker_model,
    )
    logger.info(
        "Runner settings: gold_run=%s task=%s dry_run=%s model=%s iterations=%s",
        str(config.gold_run).lower(),
        config.task,
        str(config.dry_run).lower(),
        config.model,
        config.max_iterations,
    )
    logger.info(
        "Emulator: %s/%s",
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


def _load_bundle_attacker_model(
    project_root: Path, app_name: str, config: RunnerConfig
) -> str:
    """Return the bundle's authoritative attacker_model for redteam runs.

    Bundle-backed (synthetic / zeroday): read from task metadata.json.
    Probe-only bundle-less: returns the config value (the bundle echoes it).
    """
    from evaluation.task_bundle import assert_zerodays_initialized, resolve_bundle

    if getattr(config, "task", None):
        assert_zerodays_initialized(project_root)
    return resolve_bundle(config, project_root, app_name).attacker_model()


def _log_evaluation_result(evaluation: dict) -> None:
    """Log a normalized evaluation summary."""
    logger.info(
        "Evaluation complete: status=%s score=%s reason=%s",
        evaluation.get("status"),
        evaluation.get("score"),
        evaluation.get("reason"),
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

    gold_source_dir: Optional[Path] = None
    replay_source_dir: Optional[Path] = None
    try:
        # Initialize submodules before any task/app metadata reads. Redteam
        # attacker-model reconciliation and gold-source resolution both touch
        # task bundle paths, so preconditions belong at the top of the run.
        if config.workflow == "redteam" and config.task:
            ensure_zerodays_submodule(project_root)
        ensure_app_submodule(project_root, app_name)

        # Redteam: bundle owns attacker_model. Sync into config so downstream
        # gold-source resolution sees the authoritative value.
        if config.workflow == "redteam":
            bundle_attacker_model = _load_bundle_attacker_model(
                project_root, app_name, config
            )
            if bundle_attacker_model != config.attacker_model:
                logger.info(
                    "Bundle attacker_model overrides config: %s -> %s",
                    config.attacker_model,
                    bundle_attacker_model,
                )
                config = config.model_copy(
                    update={"attacker_model": bundle_attacker_model}
                )

        # Gold source is resolved after attacker_model reconciliation so
        # shape validation uses the authoritative model.
        is_apk_exploit = (
            config.workflow == "redteam" and config.attacker_model == "malicious_app"
        )
        if config.gold_run:
            gold_source_dir = resolve_gold_source(
                workflow=config.workflow,
                app_name=app_name,
                task=config.task,
                vuln_id=None,
                project_root=project_root,
                is_apk_exploit=is_apk_exploit,
            )
        elif config.replay_exploit_dir:
            # Stage-2-only ("replay") mode: reuse a previously-saved
            # agent_exploit/ instead of running the agent. Accept either the
            # agent_exploit dir itself or a run-log dir that contains one.
            replay_source_dir = Path(config.replay_exploit_dir)
            if (replay_source_dir / "agent_exploit").is_dir():
                replay_source_dir = replay_source_dir / "agent_exploit"
            if not replay_source_dir.is_dir():
                raise ValueError(
                    "replay_exploit_dir does not exist or is not a directory: "
                    f"{config.replay_exploit_dir}"
                )

        workflow = create_workflow(config, app_name, project_root)
        workflow_type = type(workflow).__name__
        logger.info(f"Created {workflow_type} for app: {app_name}")

        logger.info("Validating arguments...")
        workflow.validate_arguments()
        logger.info("Arguments validated")

        # Log structured experiment configuration for observability
        _log_experiment_config(config, app_name, workflow)

        logger.info("Setting up runtime environment...")
        workflow.setup_runtime_environment()
        logger.info("Runtime environment ready")

        if gold_source_dir:
            staged = stage_exploit_source(
                gold_source_dir,
                workflow,
                logs_dir=logger_manager.get_logs_dir(),
                project_root=project_root,
                is_apk_exploit=is_apk_exploit,
            )
            logger.info("Staged gold exploit into %s", staged)
        elif replay_source_dir:
            # Copy the saved artifact straight into the fresh run's logs dir;
            # evaluate() reads logs_dir/agent_exploit/. No kali staging needed.
            replay_dest = logger_manager.get_logs_dir() / "agent_exploit"
            if replay_dest.exists():
                shutil.rmtree(replay_dest)
            shutil.copytree(replay_source_dir, replay_dest)
            if is_apk_exploit:
                # Build the agent's source with the CURRENT canonical script,
                # exactly like live/gold staging — never the (possibly stale or
                # unstaged) script saved next to the exploit. Makes the regrade
                # build identical to the live grade and immune to a broken/missing
                # staged build script.
                overlay_canonical_build_script(replay_dest, project_root)
            logger.info(
                "Staged saved exploit for replay: %s -> %s",
                replay_source_dir,
                replay_dest,
            )

        if config.dry_run:
            logger.info("Dry run mode - launching interactive shell...")
            run_result = normalize_agent_result(run_interactive_shell(app_name))
            run_result["status"] = "dry_run_completed"
            logger.info("Interactive shell exited")
            outcome = "success"
            exit_reason = "dry_run_completed"
            exit_code = 0
        elif gold_source_dir or replay_source_dir:
            mode = "gold-run" if gold_source_dir else "replay"
            logger.info("%s mode — evaluating prestaged exploit artifact...", mode)
            evaluation = workflow.evaluate() or {}
            _log_evaluation_result(evaluation)
            exit_reason = (
                "gold_run_completed" if gold_source_dir else "replay_completed"
            )
            run_result = normalize_agent_result({"status": "completed"})
            run_result["status"] = exit_reason
            score = evaluation.get("score")
            outcome = "success" if score == 1 else "failure"
            exit_code = 0 if score == 1 else 1
        else:
            logger.info("Configuring agent...")
            workflow.setup_agent()
            logger.info("Agent configured")

            logger.info("Starting agent execution...")
            try:
                run_result = normalize_agent_result(workflow.run_agent())
            finally:
                # Always extract artifacts and tear down the container, even
                # if run_agent() raised. Without this, a transient API error
                # or content-policy flag would destroy the agent's working
                # tree inside /app/agent_exploit/ before we copied it out.
                workflow.save_artifacts(logger_manager.get_logs_dir())
                if workflow.agent_env:
                    run_result.setdefault("agent_image", workflow.agent_env.image_name)
                    run_result.setdefault(
                        "agent_image_digest", workflow.agent_env.image_digest
                    )
                    workflow.agent_env.cleanup()
                    workflow.agent_env = None

            logger.info("Evaluating results...")
            evaluation = workflow.evaluate() or {}
            _log_evaluation_result(evaluation)

            # Derive outcome from agent_status and evaluation rather than
            # unconditionally reporting success.
            agent_status = run_result.get("status", "unknown")
            eval_score = evaluation.get("score")

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
            elif config.workflow == "redteam":
                # Redteam evaluation must always produce a top-level score.
                outcome = "failure"
                exit_reason = "missing_evaluation"
                exit_code = 1
            else:
                # No evaluation score (non-exploit workflow or eval skipped)
                outcome = "success"
                exit_reason = "completed"
                exit_code = 0

    except (ValueError, ExploitSourceError) as e:
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
        time_tracker.log_summary(logger, start_idx=timing_start_idx)

        # Always cleanup resources (emulator, containers, restore APKs)
        logger.info("Cleaning up resources...")

        # Skip this salvage save when the exploit was prestaged (gold/replay)
        # rather than produced by an agent run. The agent never ran, so the
        # container's /app/agent_exploit/ holds only setup-time scaffolding
        # (empty for RA; the malicious_app template for MA). save_artifacts
        # would extract that over logs_dir/agent_exploit/ — overwriting the
        # artifact we just staged and evaluated. The agent path saves its own
        # artifacts in its inner finally and nulls agent_env, so it never
        # reaches here.
        prestaged = bool(gold_source_dir or replay_source_dir)
        if workflow and workflow.agent_env and not prestaged:
            try:
                workflow.save_artifacts(logger_manager.get_logs_dir())
            except Exception as e:
                logger.warning(f"Failed to save artifacts before cleanup: {e}")

        # Write run_summary.json before logcat capture and workflow.cleanup so
        # the run dir always has a summary on disk if a downstream cleanup
        # step is interrupted. The canonical final write at the end of this
        # block overwrites it once cleanup completes — fields known only
        # post-cleanup (e.g. android_system.log artifact pointer) land then.
        # exit_reason is "in_progress_cleanup" only when the main try block
        # didn't set one (caller was killed before reaching the assignment).
        # Best-effort: never raises.
        try:
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
                exit_reason=exit_reason or "in_progress_cleanup",
                started_at=started_at,
                ended_at=utc_now_iso(),
                start_error_count=start_error_count,
                timing_start_idx=timing_start_idx,
            )
        except Exception as e:
            logger.warning(f"Failed early-write run_summary.json: {e}")

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

        # Final canonical write: overwrites the early defensive write above
        # with the post-cleanup state.
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
        help="Name of the app to evaluate",
    )
    parser.add_argument(
        "--config",
        default="runner_config.json",
        help="Path to runner config file",
    )
    parser.add_argument(
        "--explain-config",
        action="store_true",
        help=(
            "Print the JSON Schema for runner_config.json (field names, "
            "types, defaults, descriptions) and exit. Same content as "
            "schemas/runner_config.schema.json; useful for sweep tooling "
            "or when you do not want to leave the terminal."
        ),
    )
    parser.add_argument(
        "--explain-batch-config",
        action="store_true",
        help=(
            "Print the JSON Schema for a top-level runner config with a "
            "batch block and exit."
        ),
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help=(
            "Run the top-level batch block from the config sequentially. "
            "If app_name is omitted and the config contains batch, this is "
            "implied."
        ),
    )
    args = parser.parse_args()

    if args.explain_config:
        print(RunnerConfig.render_json_schema(), end="")
        return 0
    if args.explain_batch_config:
        print(BatchRunnerConfig.render_json_schema(), end="")
        return 0

    config_path = Path(args.config)
    try:
        has_batch = config_file_has_batch(config_path)
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        return 1

    wants_batch = args.batch or (not args.app_name and has_batch)
    if wants_batch:
        if args.app_name:
            parser.error("app_name cannot be combined with --batch; set batch.apps")
        try:
            base_config_payload, batch = load_batch_config_parts(config_path)
        except (FileNotFoundError, ValueError) as e:
            logger.error(str(e))
            return 1

        project_root = Path(__file__).parent
        try:
            return _run_batch(
                base_config_payload,
                batch,
                project_root,
                run_func=run,
                config_path=config_path,
            )
        except ValueError as e:
            logger.error(str(e))
            return 1

    if not args.app_name:
        parser.error("app_name is required unless the config contains a batch block")

    try:
        config = RunnerConfig.from_file(config_path)
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        return 1

    project_root = Path(__file__).parent

    # Initialize LoggerManager with config before any logging occurs
    from utils.logger import get_logger_manager

    get_logger_manager(config=config.model_dump(), app_name=args.app_name)

    exit_code = run(
        config,
        args.app_name,
        project_root,
        config_path=config_path,
    )

    # Print error summary at the very end for better visibility
    logger_manager.print_error_summary()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
