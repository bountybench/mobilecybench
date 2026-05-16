"""Generic BYO in-container runner.

Each reference image's ``run_in_container.py`` is ~25 lines of glue: a CLI
command builder plus a parser that knows how to consume the CLI's event
stream.

The runner owns: task.json load + schema validation, dir prep, subprocess
streaming, **incremental** writes of ``conversation.jsonl`` + ``result.json``
so a mid-stream crash or SIGTERM still leaves usable telemetry, plus the
final atomic write.
"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, List, Protocol

import jsonschema

from agent.in_container.paths import CONVERSATION_PATH, EXPLOIT_DIR, RUN_DIR
from utils.json_io import write_json_atomic

# Schema is COPY'd into every BYO image at /opt/schemas/task.schema.json
# (see agent/codex/Dockerfile and agent/claude_code/Dockerfile). The same
# PYTHONPATH=/opt convention puts this module two levels above /opt/agent/.
_SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "schemas" / "task.schema.json"
with _SCHEMA_PATH.open(encoding="utf-8") as _f:
    _TASK_VALIDATOR = jsonschema.Draft202012Validator(json.load(_f))


class Parser(Protocol):
    """Per-CLI event parser the runner delegates to.

    The runner streams CLI output through ``feed_chunk`` line by line, then
    calls ``flush`` at EOF. After every event it drains newly-flushed turns
    via ``drain_records`` into ``conversation.jsonl`` and snapshots a
    best-effort ``result.json`` via ``summarize``.
    """

    def feed_chunk(self, chunk: str) -> None: ...
    def flush(self) -> None: ...
    def drain_records(self, task: dict[str, Any]) -> List[dict[str, Any]]: ...
    def summarize(
        self, task: dict[str, Any], exit_code: int, elapsed: float
    ) -> dict[str, Any]: ...


def _load_task(task_path: str) -> dict[str, Any]:
    with open(task_path, encoding="utf-8") as f:
        task = json.load(f)
    _TASK_VALIDATOR.validate(task)
    return task


def _append_records(path: Path, records: List[dict[str, Any]]) -> None:
    """Append JSONL records. Best-effort — disk hiccup must not kill the run."""
    if not records:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _snapshot(
    result_path: Path,
    parser: Parser,
    task: dict[str, Any],
    status: str,
    elapsed: float,
    exit_code: int = 0,
) -> None:
    """Write a best-effort result.json so partial state survives crash/kill."""
    try:
        result = parser.summarize(task, exit_code, elapsed)
        result["status"] = status
        write_json_atomic(result_path, result)
    except Exception:
        pass


def run(
    task_path: str,
    *,
    parser_factory: Callable[[], Parser],
    build_cmd: Callable[[dict[str, Any]], list[str]],
) -> int:
    """Run a BYO agent. Returns the subprocess exit code (0 on success)."""
    Path(RUN_DIR).mkdir(parents=True, exist_ok=True)
    Path(EXPLOIT_DIR).mkdir(parents=True, exist_ok=True)
    result_path = Path(RUN_DIR) / "result.json"
    conv_path = Path(CONVERSATION_PATH)
    # Truncate at start so a re-run never mixes records from prior attempts.
    conv_path.write_text("", encoding="utf-8")

    try:
        task = _load_task(task_path)
    except (jsonschema.ValidationError, json.JSONDecodeError, OSError) as e:
        write_json_atomic(
            result_path,
            {
                "status": "error",
                "turns_taken": 0,
                "error_traceback": f"task.json validation failed: {e}",
            },
        )
        return 1

    parser = parser_factory()
    cmd = build_cmd(task)
    start = time.time()
    proc: subprocess.Popen[str] | None = None

    def _final_flush(status: str, exit_code: int) -> None:
        try:
            parser.flush()
        except Exception:
            pass
        _append_records(conv_path, parser.drain_records(task))
        _snapshot(result_path, parser, task, status, time.time() - start, exit_code)

    def _on_sigterm(_signum: int, _frame: Any) -> None:
        """Graceful shutdown: harness sends SIGTERM before SIGKILL (see byo_agent.run_agent)."""
        if proc is not None and proc.poll() is None:
            proc.terminate()
        _final_flush(status="timeout", exit_code=143)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _on_sigterm)

    exit_code = 1
    try:
        # Merge stderr into stdout so we read a single stream — avoids the
        # classic Popen-with-two-pipes hang where stderr fills its 64 KiB
        # buffer while the reader blocks on stdout.
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            parser.feed_chunk(line)
            new_records = parser.drain_records(task)
            if new_records:
                _append_records(conv_path, new_records)
                _snapshot(result_path, parser, task, "unknown", time.time() - start)
        parser.flush()
        exit_code = proc.wait()
    except Exception as e:
        _append_records(conv_path, parser.drain_records(task))
        write_json_atomic(
            result_path,
            {
                "status": "error",
                "turns_taken": 0,
                "error_traceback": f"subprocess error: {e}",
            },
        )
        return 1

    _final_flush(status="completed" if exit_code == 0 else "error", exit_code=exit_code)
    # Re-summarize for the true final write so exit_code/elapsed are accurate.
    write_json_atomic(
        result_path, parser.summarize(task, exit_code, time.time() - start)
    )
    return exit_code
