"""Contract self-test for ``harness.byo_agent.run_agent``.

Exercises the BYO-contract orchestration without a Docker daemon: the
container is mocked, ``get_archive`` returns synthetic tars, and the
in-process echo of what an agent would have written to /app/agent_run/
is dropped into the pulled artifact dir by the mock ``save_agent_run``.

Tests the contract surface, not Docker. Real daemon coverage is the
integration tier (run ``docker build`` against tests/byo/echo_agent/ and
exec it against a live container — outside the unit-test loop).
"""

from __future__ import annotations

import io
import json
import tarfile
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import docker.errors
import pytest

from harness.byo_agent import run_agent


def _make_env(
    tmp_path: Path,
    *,
    result_dict: dict[str, Any] | None,
    image_tag: str = "cybench/mobilecybench-echo:test",
    image_id: str = "sha256:abc123",
    exec_running_sequence: list[bool] | None = None,
    exit_code: int = 0,
    tail_chunks: list[bytes] | None = None,
    tail_create_raises: Exception | None = None,
) -> MagicMock:
    """Build a mock AgentEnvironment whose container exec_run produces the
    expected ``result.json``.

    ``exec_running_sequence`` lets the test control how many polling
    iterations happen before the main /run-agent.sh exec appears exited.
    Default: exits on the first inspect.

    ``tail_chunks`` is the byte stream produced by the live-log-mirror's
    `tail -F` exec (consumed when ``exec_start(stream=True)``). Default
    empty stream.

    ``tail_create_raises`` simulates the mirror failing to start (e.g.
    docker API error on its exec_create); main run continues unaffected.
    """
    env = MagicMock(name="AgentEnvironment")
    container = MagicMock(name="container")

    container.image.tags = [image_tag]
    container.image.id = image_id
    container.id = "ctnr-id"

    api = MagicMock(name="docker_api")
    container.client.api = api

    # exec_create is called up to three times: /run-agent.sh, tail, pkill.
    # Hand out stable IDs so exec_inspect / assertions can key by name.
    exec_ids = iter(["exec-run", "exec-tail", "exec-pkill"])

    def _exec_create(_cid: str, cmd: Any) -> dict[str, str]:
        next_id = next(exec_ids)
        if next_id == "exec-tail" and tail_create_raises is not None:
            raise tail_create_raises
        return {"Id": next_id}

    api.exec_create.side_effect = _exec_create

    def _exec_start(_exec_id: str, stream: bool = False, detach: bool = False) -> Any:
        if stream:
            return iter(tail_chunks or [])
        return None

    api.exec_start.side_effect = _exec_start

    if exec_running_sequence is None:
        exec_running_sequence = [False]

    # The grace-period loop after SIGTERM polls exec_inspect repeatedly.
    # Keep the LAST entry repeating forever so tests don't blow up with
    # StopIteration from a too-short scripted sequence.
    def _inspect_factory() -> Any:
        seq = list(exec_running_sequence)

        def _next(exec_id: str, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            if exec_id != "exec-run":
                # tail / pkill are not the lifecycle truth; report exited.
                return {"Running": False, "ExitCode": 0}
            running = seq[0] if len(seq) == 1 else seq.pop(0)
            return {"Running": running, "ExitCode": None if running else exit_code}

        return _next

    api.exec_inspect.side_effect = _inspect_factory()

    env.container = container

    # save_agent_* are the extraction sinks. Simulate them by writing the
    # synthesized result.json into the host dir, mimicking what get_archive
    # would have populated.
    def _save_agent_run(dest_dir: Path) -> None:
        run_dir = dest_dir / "agent_run"
        run_dir.mkdir(parents=True, exist_ok=True)
        if result_dict is not None:
            (run_dir / "result.json").write_text(json.dumps(result_dict))
        # Conforms to schemas/conversation_turn.schema.json.
        (run_dir / "conversation.jsonl").write_text(
            json.dumps(
                {
                    "run_id": "test-run",
                    "turn_number": 1,
                    "timestamp": "2026-05-18T00:00:00+00:00",
                    "role": "assistant",
                    "response_id": None,
                    "assistant_text": "echo done",
                    "reasoning_summary": None,
                    "tool_calls": [],
                    "observations": [],
                    "status": "ok",
                }
            )
            + "\n"
        )
        (run_dir / "agent.log").write_text("agent.log contents\n")

    def _save_agent_exploit(dest_dir: Path) -> None:
        ex_dir = dest_dir / "agent_exploit"
        ex_dir.mkdir(parents=True, exist_ok=True)
        (ex_dir / "exploit.sh").write_text("#!/usr/bin/env bash\nexit 0\n")

    def _save_agent_output(dest_dir: Path) -> None:
        out_dir = dest_dir / "agent_output"
        out_dir.mkdir(parents=True, exist_ok=True)

    env.save_agent_run.side_effect = _save_agent_run
    env.save_agent_exploit.side_effect = _save_agent_exploit
    env.save_agent_output.side_effect = _save_agent_output

    # MagicMock children don't expose __name__; production code logs fn.__name__
    # on partial-extraction failure, so we set it explicitly.
    env.save_agent_run.__name__ = "save_agent_run"
    env.save_agent_exploit.__name__ = "save_agent_exploit"
    env.save_agent_output.__name__ = "save_agent_output"

    return env


def _set_deterministic_monotonic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive time.monotonic deterministically so wallclock + grace deadlines
    fire in O(few iterations) instead of busy-waiting for real time to drift.
    Each call advances the fake clock by 100s — well past any 10s grace window.
    """
    clock = [0.0]

    def fake_monotonic() -> float:
        clock[0] += 100.0
        return clock[0]

    monkeypatch.setattr(time, "monotonic", fake_monotonic)
    monkeypatch.setattr(time, "sleep", lambda _: None)


def _task(wallclock: int = 60) -> dict[str, Any]:
    """Minimal valid task dict for run_agent."""
    return {
        "run_id": "experiment_test",
        "app_name": "fake-app",
        "workflow": "exploit",
        "probe_only": False,
        "package_name": "fake.app",
        "app_server": "fake-app:80",
        "emulator_server": "http://10.0.2.2:8080",
        "task": None,
        "vuln_id": "vuln_test",
        "apk_relpath": "",
        "no_codebase": False,
        "attacker_model": "",
        "model": "claude-sonnet-4-6",
        "prompt": "find the vuln",
        "agent_wallclock_seconds": wallclock,
        "reasoning_effort": "high",
    }


class TestRunAgentHappyPath:
    """Agent exits cleanly with valid result.json."""

    def test_completed_status_propagates(self, tmp_path: Path) -> None:
        env = _make_env(
            tmp_path,
            result_dict={
                "status": "completed",
                "turns_taken": 1,
                "cost_usd": 0.0,
                "final_message": "echo-agent finished",
            },
        )
        out = run_agent(env=env, task_dict=_task(), host_artifact_dir=tmp_path)

        assert out["status"] == "completed"
        assert out["turns_taken"] == 1
        assert out["final_message"] == "echo-agent finished"

    def test_task_json_delivered_via_put_archive(self, tmp_path: Path) -> None:
        env = _make_env(
            tmp_path,
            result_dict={"status": "completed", "turns_taken": 1},
        )
        run_agent(env=env, task_dict=_task(), host_artifact_dir=tmp_path)

        env.container.put_archive.assert_called_once()
        _, kwargs = env.container.put_archive.call_args
        assert kwargs["path"] == "/app"

        # Inspect the tar payload to verify it carries task.json with our content.
        tar_bytes = kwargs["data"]
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r") as tar:
            members = tar.getnames()
            assert members == ["task.json"]
            f = tar.extractfile("task.json")
            assert f is not None
            payload = json.loads(f.read())
            assert payload["app_name"] == "fake-app"
            assert payload["agent_wallclock_seconds"] == 60

    def test_artifacts_pulled_in_priority_order(self, tmp_path: Path) -> None:
        """agent_run is pulled FIRST so the diagnostic trail survives partial
        extraction failure."""
        env = _make_env(
            tmp_path,
            result_dict={"status": "completed", "turns_taken": 1},
        )
        run_agent(env=env, task_dict=_task(), host_artifact_dir=tmp_path)

        call_order = [m for m in env.method_calls if m[0].startswith("save_agent_")]
        names = [m[0] for m in call_order]
        assert names == ["save_agent_run", "save_agent_exploit", "save_agent_output"]

    def test_agent_image_fields_stamped(self, tmp_path: Path) -> None:
        env = _make_env(
            tmp_path,
            result_dict={"status": "completed", "turns_taken": 1},
            image_tag="cybench/mobilecybench:codex_2.5.0",
            image_id="sha256:deadbeef",
        )
        out = run_agent(env=env, task_dict=_task(), host_artifact_dir=tmp_path)

        assert out["agent_image"] == "cybench/mobilecybench:codex_2.5.0"
        assert out["agent_image_digest"] == "sha256:deadbeef"


class TestRunAgentFailureModes:
    """Missing result.json, malformed JSON, daemon errors, timeouts."""

    def test_missing_result_json_yields_error(self, tmp_path: Path) -> None:
        env = _make_env(tmp_path, result_dict=None)  # no result.json written
        out = run_agent(env=env, task_dict=_task(), host_artifact_dir=tmp_path)

        assert out["status"] == "error"
        assert "without writing result.json" in out["error_traceback"]

    def test_malformed_result_json_yields_error(self, tmp_path: Path) -> None:
        env = _make_env(tmp_path, result_dict=None)

        # Override save_agent_run to write garbage JSON.
        def _save_garbage(dest_dir: Path) -> None:
            run_dir = dest_dir / "agent_run"
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "result.json").write_text("not valid json {{{")

        env.save_agent_run.side_effect = _save_garbage

        out = run_agent(env=env, task_dict=_task(), host_artifact_dir=tmp_path)

        assert out["status"] == "error"
        assert "malformed" in out["error_traceback"]

    def test_timeout_sends_sigterm_then_sigkill_when_grace_expires(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When wall-clock expires, SIGTERM is sent first; if the agent
        doesn't exit within the grace window, SIGKILL escalates and the
        result synthesizes as ``timeout``."""
        env = _make_env(
            tmp_path,
            result_dict=None,
            exec_running_sequence=[True],  # stays Running through grace → SIGKILL
        )
        _set_deterministic_monotonic(monkeypatch)

        out = run_agent(
            env=env, task_dict=_task(wallclock=60), host_artifact_dir=tmp_path
        )

        env.container.exec_run.assert_any_call(
            ["pkill", "-TERM", "-f", r"agent\..*\.run_in_container"]
        )
        env.container.kill.assert_called_once_with(signal="SIGKILL")
        assert out["status"] == "timeout"

    def test_timeout_overrides_stale_unknown_snapshot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Per-chunk snapshots write status='unknown'. When SIGKILL pre-empts
        # the in-container SIGTERM flush, that stale value lands on disk.
        # Host overrides to 'timeout' since it knows it killed the run.
        env = _make_env(
            tmp_path,
            result_dict={"status": "unknown", "turns_taken": 39},
            exec_running_sequence=[True],
        )
        _set_deterministic_monotonic(monkeypatch)

        out = run_agent(
            env=env, task_dict=_task(wallclock=60), host_artifact_dir=tmp_path
        )

        env.container.kill.assert_called_once_with(signal="SIGKILL")
        assert out["status"] == "timeout"
        assert out["turns_taken"] == 39

    def test_timeout_preserves_in_container_finalized_status(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Counterpart to the override: when the SIGTERM handler had time to
        # finalize, that status is authoritative — host must not relabel.
        env = _make_env(
            tmp_path,
            result_dict={
                "status": "completed",
                "turns_taken": 7,
                "final_message": "done",
            },
            exec_running_sequence=[True, False],  # SIGTERM then graceful exit
        )
        _set_deterministic_monotonic(monkeypatch)

        out = run_agent(
            env=env, task_dict=_task(wallclock=60), host_artifact_dir=tmp_path
        )

        # Status preserved from the in-container finalization; host doesn't relabel.
        assert out["status"] == "completed"
        assert out["turns_taken"] == 7

    def test_timeout_sigterm_graceful_exit_skips_sigkill(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the agent exits cleanly after SIGTERM, SIGKILL is NOT sent."""
        env = _make_env(
            tmp_path,
            result_dict={"status": "timeout", "turns_taken": 2},
            # First inspect: Running (wait phase detects timeout).
            # Second inspect (in grace loop): exited → break, no SIGKILL.
            exec_running_sequence=[True, False],
        )
        _set_deterministic_monotonic(monkeypatch)

        run_agent(env=env, task_dict=_task(wallclock=60), host_artifact_dir=tmp_path)

        env.container.exec_run.assert_any_call(
            ["pkill", "-TERM", "-f", r"agent\..*\.run_in_container"]
        )
        env.container.kill.assert_not_called()

    def test_partial_extraction_failure_preserves_others(self, tmp_path: Path) -> None:
        """save_agent_exploit raises; save_agent_run + save_agent_output still
        run and the result is salvaged."""
        env = _make_env(
            tmp_path,
            result_dict={"status": "completed", "turns_taken": 1},
        )
        env.save_agent_exploit.side_effect = RuntimeError("exploit pull failed")

        out = run_agent(env=env, task_dict=_task(), host_artifact_dir=tmp_path)

        # agent_run was still pulled (result.json read works).
        assert out["status"] == "completed"
        # All three were attempted.
        assert env.save_agent_run.called
        assert env.save_agent_exploit.called
        assert env.save_agent_output.called


class TestLiveLogMirror:
    """Live mirroring of /app/agent_run/agent.log to host agent_logger."""

    @pytest.fixture(autouse=True)
    def _skip_drain_sleep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Mirror teardown sleeps 0.5s to drain the tail socket; tests don't
        # need to wait real-time for that.
        monkeypatch.setattr(time, "sleep", lambda _: None)

    def test_emits_external_lines_via_agent_logger(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        env = _make_env(
            tmp_path,
            result_dict={"status": "completed", "turns_taken": 1},
            tail_chunks=[b"hello world\n", b"second line\n"],
        )

        with caplog.at_level("INFO"):
            out = run_agent(env=env, task_dict=_task(), host_artifact_dir=tmp_path)

        external = [
            r.getMessage()
            for r in caplog.records
            if "[External Agent]" in r.getMessage()
        ]
        assert "[External Agent] hello world" in external
        assert "[External Agent] second line" in external
        assert out["status"] == "completed"

    def test_mirror_start_failure_does_not_break_run(self, tmp_path: Path) -> None:
        """Second exec_create (tail) raises APIError. The first exec_create
        is /run-agent.sh; failure to start the live mirror must not affect
        the main agent run."""
        env = _make_env(
            tmp_path,
            result_dict={"status": "completed", "turns_taken": 1},
            tail_create_raises=docker.errors.APIError("tail exec_create failed"),
        )

        out = run_agent(env=env, task_dict=_task(), host_artifact_dir=tmp_path)

        assert out["status"] == "completed"

    def test_mirror_pkill_completes_before_artifact_pull(self, tmp_path: Path) -> None:
        """Blocking pkill (exec_start with detach=False) must finish before
        _save_container_dir extracts the tar over the host's agent_run/agent.log
        path; otherwise the still-live tail pump races the extract.

        Asserting on `exec_create` ordering alone is insufficient — a later
        change flipping pkill to `detach=True` would slip past that check
        while reintroducing the race. We assert on `exec_start(exec-pkill,
        detach=False)` instead.
        """
        env = _make_env(
            tmp_path,
            result_dict={"status": "completed", "turns_taken": 1},
            tail_chunks=[b"line\n"],
        )

        ordered: list[str] = []

        api = env.container.client.api
        original_start = api.exec_start.side_effect

        def _start_tracking(
            exec_id: str, stream: bool = False, detach: bool = False
        ) -> Any:
            if exec_id == "exec-pkill":
                ordered.append("pkill_blocking" if not detach else "pkill_detached")
            return original_start(exec_id, stream=stream, detach=detach)

        api.exec_start.side_effect = _start_tracking

        def _save_run(_dest: Path) -> None:
            ordered.append("save_agent_run")

        env.save_agent_run.side_effect = _save_run

        run_agent(env=env, task_dict=_task(), host_artifact_dir=tmp_path)

        assert "pkill_blocking" in ordered, f"pkill must be blocking; got: {ordered}"
        assert "save_agent_run" in ordered
        assert ordered.index("pkill_blocking") < ordered.index("save_agent_run")
