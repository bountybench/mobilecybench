"""Run an external (BYO-contract) agent inside an already-prepared container.

Single function: ``run_agent(env, task_dict, host_artifact_dir) -> dict``.

The container is created upstream by ``setup_runtime_environment`` from
``config.agent_image``; ``env.container`` is the live handle and
``env.container.image`` is the source of truth for which image is running.
"""

from __future__ import annotations

import io
import json
import logging
import tarfile
import time
from pathlib import Path
from typing import Any

import docker.errors

from harness import paths
from utils.run_artifacts import normalize_agent_result

logger = logging.getLogger(__name__)

# How often to poll exec_inspect during agent execution. 250ms balances
# responsiveness on the SIGKILL deadline against Docker daemon round-trip cost.
_POLL_INTERVAL_SECONDS = 0.25


def _put_task_json(container, task_dict: dict[str, Any]) -> None:
    """Deliver task_dict to ``paths.TASK_JSON`` inside the running container.

    No bind-mount: ``put_archive`` writes the file post-start so the task
    contents are decoupled from container creation ordering.
    """
    target_path = Path(paths.TASK_JSON)
    target_dir = str(target_path.parent)
    target_name = target_path.name

    payload = json.dumps(task_dict, indent=2).encode("utf-8")

    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as tar:
        info = tarfile.TarInfo(name=target_name)
        info.size = len(payload)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(payload))
    tar_stream.seek(0)

    # put_archive extracts the tar into the target directory.
    container.put_archive(path=target_dir, data=tar_stream.getvalue())


def _wait_for_exec(api, exec_id: str, deadline: float) -> tuple[bool, int | None]:
    """Poll exec_inspect until process exits or deadline reached.

    Returns ``(timed_out, exit_code)``. ``exit_code`` is None on timeout
    (process forcibly killed) or if the daemon hasn't recorded one yet.
    """
    while True:
        info = api.exec_inspect(exec_id)
        if not info.get("Running"):
            return False, info.get("ExitCode")
        if time.monotonic() >= deadline:
            return True, None
        time.sleep(_POLL_INTERVAL_SECONDS)


def _pull_artifacts(env, host_artifact_dir: Path) -> None:
    """Extract all three contract directories in priority order.

    Order matters: agent_run/ first (carries result.json, conversation.jsonl,
    agent.log — the diagnostic trail we need even when other extraction
    fails), then agent_exploit/ (work-product), then agent_output/
    (evidence). Each call wrapped so a partial failure doesn't block
    the others (matches today's save_artifacts best-effort pattern).
    """
    for fn in (env.save_agent_run, env.save_agent_exploit, env.save_agent_output):
        try:
            fn(host_artifact_dir)
        except Exception as e:
            logger.warning(f"Failed to save via {fn.__name__}: {e}")


def _read_result_json(host_artifact_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read the pulled-back result.json.

    Returns ``(parsed_dict, error_message)``. On success, ``error_message``
    is None. On missing file, both are None. On malformed JSON, dict is
    None and error_message carries the decoder message.
    """
    result_path = host_artifact_dir / "agent_run" / "result.json"
    if not result_path.exists():
        return None, None
    try:
        return json.loads(result_path.read_text()), None
    except json.JSONDecodeError as e:
        return None, f"result.json malformed: {e}"


def _synthesize_result(
    *,
    timed_out: bool,
    exit_code: int | None,
    decoder_error: str | None,
    daemon_error: str | None,
) -> dict[str, Any]:
    """Build a result dict when the agent didn't write a valid result.json.

    Status precedence: daemon_error > decoder_error > timeout > error.
    """
    if daemon_error:
        return {"status": "error", "error_traceback": daemon_error, "turns_taken": 0}
    if decoder_error:
        return {"status": "error", "error_traceback": decoder_error, "turns_taken": 0}
    if timed_out:
        return {"status": "timeout", "turns_taken": 0}
    # Process exited but no result.json. Treat as error with exit code.
    return {
        "status": "error",
        "error_traceback": f"agent exited (code={exit_code}) without writing result.json",
        "exit_code": exit_code or 0,
        "turns_taken": 0,
    }


def run_agent(
    *,
    env,
    task_dict: dict[str, Any],
    host_artifact_dir: Path,
) -> dict[str, Any]:
    """Run an external agent and return its normalized result.

    Lifecycle (see ``documentation/proposals/agent_decoupling/06_design.md`` §2.4):

    1. ``put_archive`` delivers ``task_dict`` as JSON to ``/app/task.json``.
    2. Detached ``docker exec /run-agent.sh``; poll until exit or deadline.
    3. On deadline: ``container.kill(signal="SIGKILL")``. Hard kill pid 1;
       Docker doesn't propagate signals reliably, so we don't try grace.
    4. ``finally``: pull agent_run/, agent_exploit/, agent_output/ in
       priority order. Each call wrapped so partial failure preserves
       what we can salvage.
    5. Read result.json, validate + normalize.

    Args:
        env: ``AgentEnvironment`` with a live ``env.container``.
        task_dict: Validated task dict from ``harness.task.build_task_dict``.
        host_artifact_dir: Destination for pulled artifacts (typically
            ``logs/experiment_<uuid>/``).

    Returns:
        Normalized result dict with ``status``, ``turns_taken``, plus
        ``agent_image``, ``agent_image_digest``, and ``host_paths``.
    """
    container = env.container
    api = container.client.api  # type: ignore[attr-defined]

    wallclock_seconds = task_dict["agent_wallclock_seconds"]
    deadline = time.monotonic() + wallclock_seconds

    timed_out = False
    exit_code: int | None = None
    daemon_error: str | None = None

    try:
        try:
            _put_task_json(container, task_dict)
            exec_id = api.exec_create(container.id, "/run-agent.sh")["Id"]
            api.exec_start(exec_id, detach=True)
            timed_out, exit_code = _wait_for_exec(api, exec_id, deadline)
            if timed_out:
                logger.warning(
                    f"Agent exceeded {wallclock_seconds}s wall-clock; "
                    "sending SIGKILL to container."
                )
                container.kill(signal="SIGKILL")
        except docker.errors.APIError as e:
            daemon_error = f"docker.errors.APIError: {e}"
            logger.error(daemon_error)
    finally:
        _pull_artifacts(env, host_artifact_dir)

    raw, decoder_error = _read_result_json(host_artifact_dir)
    if raw is None:
        raw = _synthesize_result(
            timed_out=timed_out,
            exit_code=exit_code,
            decoder_error=decoder_error,
            daemon_error=daemon_error,
        )

    result = normalize_agent_result(raw)

    # Stamp the image-identity fields so write_run_summary picks them up.
    image = container.image
    result["agent_image"] = image.tags[0] if image.tags else image.id
    result["agent_image_digest"] = image.id
    result["host_paths"] = {
        "agent_run": str(host_artifact_dir / "agent_run"),
        "agent_exploit": str(host_artifact_dir / "agent_exploit"),
        "agent_output": str(host_artifact_dir / "agent_output"),
    }
    return result
