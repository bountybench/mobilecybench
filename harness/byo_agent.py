"""Run an external (BYO-contract) agent inside an already-prepared container.

Single function: ``run_agent(env, task_dict, host_artifact_dir) -> dict``.

The container is created upstream by ``setup_runtime_environment`` from
``config.agent_image``; ``env.container`` is the live handle and
``env.container.image`` is the source of truth for which image is running.
"""

from __future__ import annotations

import io
import json
import tarfile
import threading
import time
from pathlib import Path
from typing import Any

import docker.errors

from agent.in_container.paths import TASK_JSON
from utils.logger import agent_logger, logger

# Matches utils.docker_utils.run_command_in_container's polling cadence.
_POLL_INTERVAL_SECONDS = 1.0

# Window the in-container runner.py has to handle SIGTERM and flush
# conversation.jsonl + result.json before we escalate to SIGKILL.
_GRACEFUL_STOP_SECONDS = 10.0

# Live mirror of /app/agent_run/agent.log to host operator. Best-effort
# observability layer; canonical artifact is still the post-run pull.
_TAIL_CMD = ["sh", "-lc", "tail -n +1 -F /app/agent_run/agent.log 2>/dev/null"]
# pkill -f matches a regex; [t] avoids self-matching the pkill grep,
# and \+ escapes the regex metachar in the tail flag.
_TAIL_PATTERN = r"[t]ail -n \+1 -F /app/agent_run"
# Flush an unterminated buffer when it grows past this size so a runaway
# agent emitting bytes without newlines can't bloat host memory.
_BUF_FLUSH_BYTES = 64 * 1024
# Window for last tail bytes to drain to the docker stream socket before
# we kill tail.
_MIRROR_DRAIN_SECONDS = 0.5


def _put_task_json(container, task_dict: dict[str, Any]) -> None:
    """Deliver task_dict to /app/task.json via put_archive (no bind-mount)."""
    target = Path(TASK_JSON)
    payload = json.dumps(task_dict, indent=2).encode("utf-8")

    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as tar:
        info = tarfile.TarInfo(name=target.name)
        info.size = len(payload)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(payload))
    container.put_archive(path=str(target.parent), data=tar_stream.getvalue())


class _LogMirror:
    """Best-effort live mirror of container `agent.log` to host `agent_logger`.

    Uses only the low-level docker APIClient; failures cannot break the
    main agent run.
    """

    def __init__(self, api, container_id: str):
        self._api = api
        self._container_id = container_id
        self._exec_id: str | None = None
        self._stream = None
        self._thread: threading.Thread | None = None
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    def start(self) -> None:
        try:
            self._exec_id = self._api.exec_create(self._container_id, _TAIL_CMD)["Id"]
            self._stream = self._api.exec_start(self._exec_id, stream=True)
        except Exception as e:
            logger.warning("live log mirror failed to start: %s", e)
            return
        self._thread = threading.Thread(
            target=self._pump, daemon=True, name="byo-log-mirror"
        )
        self._started = True
        self._thread.start()

    def _pump(self) -> None:
        stream = self._stream
        if stream is None:
            return
        buf = b""
        try:
            for chunk in stream:
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    agent_logger.info(
                        "[External Agent] %s", line.decode(errors="replace")
                    )
                if len(buf) >= _BUF_FLUSH_BYTES:
                    agent_logger.info(
                        "[External Agent] %s", buf.decode(errors="replace")
                    )
                    buf = b""
            if buf:
                agent_logger.info("[External Agent] %s", buf.decode(errors="replace"))
        except Exception as e:
            logger.debug("live log mirror stream ended: %s", e)

    def stop(self) -> None:
        # Blocking pkill: tail -F never EOFs on its own, and if we let
        # the artifact tar extraction run while the pump is still writing
        # to host agent_run/agent.log the two writers race over the same
        # file (agent/runtime/container.py:637).
        try:
            kill_id = self._api.exec_create(
                self._container_id, ["pkill", "-f", _TAIL_PATTERN]
            )["Id"]
            self._api.exec_start(kill_id, detach=False)
        except Exception as e:
            logger.debug("live log mirror pkill failed: %s", e)
        try:
            close = getattr(self._stream, "close", None)
            if close:
                close()
        except Exception as e:
            logger.debug("live log mirror stream close failed: %s", e)

    def join(self, timeout: float) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)


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
    """agent_run/ first so the diagnostic trail survives partial failure."""
    for fn in (env.save_agent_run, env.save_agent_exploit, env.save_agent_output):
        try:
            fn(host_artifact_dir)
        except Exception as e:
            logger.warning(f"Failed to save via {fn.__name__}: {e}")


def _read_result_json(
    host_artifact_dir: Path,
) -> tuple[dict[str, Any] | None, str | None]:
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
    """Build a result dict when the agent didn't write a valid result.json."""
    if daemon_error:
        return {"status": "error", "error_traceback": daemon_error, "turns_taken": 0}
    if decoder_error:
        return {"status": "error", "error_traceback": decoder_error, "turns_taken": 0}
    if timed_out:
        return {"status": "timeout", "turns_taken": 0}
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
    """Run an external agent inside ``env.container`` and return its normalized result."""
    container = env.container
    api = container.client.api  # type: ignore[attr-defined]

    wallclock_seconds = task_dict["agent_wallclock_seconds"]
    deadline = time.monotonic() + wallclock_seconds

    timed_out = False
    exit_code: int | None = None
    daemon_error: str | None = None

    mirror = _LogMirror(api, container.id)

    try:
        try:
            _put_task_json(container, task_dict)
            exec_id = api.exec_create(container.id, "/run-agent.sh")["Id"]
            api.exec_start(exec_id, detach=True)
            mirror.start()
            timed_out, exit_code = _wait_for_exec(api, exec_id, deadline)
            if timed_out:
                # Two-phase termination: SIGTERM first so the in-container
                # runner's signal handler can flush conversation.jsonl and
                # write result.json with status="timeout" (see
                # agent/in_container/runner.py::_on_sigterm). SIGKILL only if
                # the agent doesn't exit within the grace window.
                logger.warning(
                    f"Agent exceeded {wallclock_seconds}s wall-clock; "
                    "sending SIGTERM to runner for graceful flush."
                )
                try:
                    # Reference images launch as `python -m agent.<cli>.run_in_container`;
                    # match that argv so the runner's SIGTERM handler fires.
                    container.exec_run(
                        ["pkill", "-TERM", "-f", r"agent\..*\.run_in_container"]
                    )
                except docker.errors.APIError as e:
                    logger.debug("pkill SIGTERM via exec_run failed: %s", e)
                grace_expired, _ = _wait_for_exec(
                    api, exec_id, time.monotonic() + _GRACEFUL_STOP_SECONDS
                )
                if grace_expired:
                    logger.warning(
                        f"Agent did not exit within {_GRACEFUL_STOP_SECONDS}s "
                        "of SIGTERM; sending SIGKILL to container."
                    )
                    container.kill(signal="SIGKILL")
        except docker.errors.APIError as e:
            daemon_error = f"docker.errors.APIError: {e}"
            logger.error(daemon_error)
    finally:
        if mirror.started:
            time.sleep(_MIRROR_DRAIN_SECONDS)  # let final tail bytes reach the socket
            mirror.stop()
            mirror.join(timeout=_MIRROR_DRAIN_SECONDS)
        _pull_artifacts(env, host_artifact_dir)

    raw, decoder_error = _read_result_json(host_artifact_dir)
    synthesized = raw is None
    if synthesized:
        raw = _synthesize_result(
            timed_out=timed_out,
            exit_code=exit_code,
            decoder_error=decoder_error,
            daemon_error=daemon_error,
        )

    # SIGKILL can fire before the in-container runner's SIGTERM handler
    # writes a final status, leaving the in-flight "unknown" snapshot on
    # disk. Override only that stale case; preserve real completed/error
    # statuses the runner finalized in time, and preserve daemon_error /
    # decoder_error precedence from _synthesize_result.
    if timed_out and not synthesized and raw.get("status") == "unknown":
        raw["status"] = "timeout"

    # Stamp the image-identity fields so write_run_summary picks them up.
    # Returns the raw dict; runner-side normalize_agent_result is the single
    # validation + cost-resolution boundary.
    image = container.image
    raw["agent_image"] = image.tags[0] if image.tags else image.id
    raw["agent_image_digest"] = image.id
    return raw
