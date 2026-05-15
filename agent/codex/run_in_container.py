"""In-container entrypoint for the codex BYO-contract image.

Reads /app/task.json, spawns `codex exec` as a subprocess, streams its
JSONL events through the shared CodexEventParser, emits conversation.jsonl
per turn, and writes result.json atomically.
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import jsonschema

from agent.codex.event_parser import CodexEventParser
from utils.json_io import write_json_atomic

# Schema lives at /opt/schemas/ in the image (Dockerfile.codex COPYs it
# alongside agent/). Load at import; both the validator and the schema
# itself are read-only.
_TASK_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent / "schemas" / "task.schema.json"
)
with _TASK_SCHEMA_PATH.open(encoding="utf-8") as _f:
    _TASK_VALIDATOR = jsonschema.Draft202012Validator(json.load(_f))

TASK_JSON = "/app/task.json"
EXPLOIT_DIR = "/app/agent_exploit"
RUN_DIR = "/app/agent_run"
CONVERSATION_PATH = f"{RUN_DIR}/conversation.jsonl"


def _load_task(task_path: str) -> dict[str, Any]:
    with open(task_path, encoding="utf-8") as f:
        task = json.load(f)
    _TASK_VALIDATOR.validate(task)
    return task


def _build_codex_command(task: dict[str, Any]) -> list[str]:
    """codex exec command line from task fields.

    Maps:
      task.model -> -c model='<id>'
      task.reasoning_effort -> -c model_reasoning_effort='<level>' (skip when null)
      task.no_codebase -> working dir /app/apk vs /app/codebase
      task.prompt -> trailing positional arg
    """
    config: dict[str, Any] = {
        "history.persistence": "none",
        "tui.animations": False,
        "tui.notifications": False,
        "approval_policy": "never",
        "sandbox_mode": "danger-full-access",
        "model_reasoning_summary": "detailed",
        "model_verbosity": "high",
    }
    if task.get("model"):
        config["model"] = task["model"]
    if task.get("reasoning_effort") is not None:
        config["model_reasoning_effort"] = task["reasoning_effort"]

    cmd = ["stdbuf", "-oL", "-eL", "codex"]
    for key, val in config.items():
        if isinstance(val, bool):
            toml_val = "true" if val else "false"
        elif isinstance(val, str):
            toml_val = f"'{val}'"
        else:
            toml_val = str(val)
        cmd.extend(["--config", f"{key}={toml_val}"])

    working_dir = "/app/apk" if task["no_codebase"] else "/app/codebase"
    cmd.extend(
        [
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "--json",
            "-C",
            working_dir,
            task["prompt"],
        ]
    )
    return cmd


def _emit_conversation_turns(task: dict[str, Any], parser: CodexEventParser) -> None:
    """Materialize parser.conversation_events to conversation.jsonl.

    Adds the schema fields the harness-side conversation_turn schema expects
    (run_id, timestamp, role=assistant, response_id=None, reasoning_summary).
    """
    run_id = task["run_id"]
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(CONVERSATION_PATH, "w", encoding="utf-8") as f:
        for ev in parser.conversation_events:
            turn_event = {
                "run_id": run_id,
                "turn_number": ev["turn"],
                "timestamp": timestamp,
                "role": "assistant",
                "response_id": None,
                "assistant_text": ev["assistant_text"],
                "reasoning_summary": "",
                "tool_calls": ev["tool_calls"],
                "observations": ev["observations"],
                "status": "ok",
            }
            f.write(json.dumps(turn_event, ensure_ascii=False) + "\n")


def main(argv: list[str]) -> int:
    task_path = argv[1] if len(argv) > 1 else TASK_JSON

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

    parser = CodexEventParser()
    cmd = _build_codex_command(task)

    start = time.time()
    exit_code = 1
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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
                "turns_taken": parser.turn_count,
                "error_traceback": f"codex subprocess error: {e}",
            },
        )
        return 1

    _emit_conversation_turns(task, parser)

    elapsed = time.time() - start
    status = "completed" if exit_code == 0 else "error"
    result: dict[str, Any] = {
        "status": status,
        "turns_taken": parser.turn_count,
        "cost_usd": 0,
        "model": task.get("model", ""),
        "final_message": parser.final_output,
        "tool_call_count": sum(parser.tool_call_breakdown.values()),
        "unique_tools": sorted(parser.tool_call_breakdown.keys()),
        "token_totals": parser.token_usage,
        "exit_code": exit_code,
    }
    if status == "error":
        result["error_traceback"] = (
            f"codex exit_code={exit_code}, elapsed={elapsed:.1f}s"
        )

    write_json_atomic(result_path, result)
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
