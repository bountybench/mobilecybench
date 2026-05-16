"""Generic BYO in-container runner.

Each reference image's ``run_in_container.py`` is ~25 lines of glue: a CLI
command builder plus a parser that knows how to consume the CLI's event
stream and emit ``conversation.jsonl`` + ``result.json``.

The runner owns: task.json load + schema validation, dir prep, subprocess
streaming, error-paths, and the final atomic write.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Protocol

import jsonschema

from utils.json_io import write_json_atomic

EXPLOIT_DIR = "/app/agent_exploit"
RUN_DIR = "/app/agent_run"
CONVERSATION_PATH = f"{RUN_DIR}/conversation.jsonl"

# Schema is COPY'd into every BYO image at /opt/schemas/task.schema.json
# (see agent/codex/Dockerfile and agent/claude_code/Dockerfile). The same
# PYTHONPATH=/opt convention puts this module two levels above /opt/agent/.
_SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "schemas" / "task.schema.json"
with _SCHEMA_PATH.open(encoding="utf-8") as _f:
    _TASK_VALIDATOR = jsonschema.Draft202012Validator(json.load(_f))


class Parser(Protocol):
    """Per-CLI event parser the runner delegates to.

    The runner streams CLI output through ``feed_chunk`` line by line, calls
    ``flush`` at EOF, then asks the parser to materialize the run by writing
    ``conversation.jsonl`` and returning the ``result.json`` payload.
    """

    def feed_chunk(self, chunk: str) -> None: ...
    def flush(self) -> None: ...
    def emit_turns(self, task: dict[str, Any], path: str) -> None: ...
    def summarize(
        self, task: dict[str, Any], exit_code: int, elapsed: float
    ) -> dict[str, Any]: ...


def _load_task(task_path: str) -> dict[str, Any]:
    with open(task_path, encoding="utf-8") as f:
        task = json.load(f)
    _TASK_VALIDATOR.validate(task)
    return task


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
        parser.flush()
        exit_code = proc.wait()
    except Exception as e:
        write_json_atomic(
            result_path,
            {
                "status": "error",
                "turns_taken": 0,
                "error_traceback": f"subprocess error: {e}",
            },
        )
        return 1

    parser.emit_turns(task, CONVERSATION_PATH)
    write_json_atomic(result_path, parser.summarize(task, exit_code, time.time() - start))
    return exit_code
