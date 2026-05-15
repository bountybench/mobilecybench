"""In-container entrypoint for the claude-code BYO-contract image.

Reads /app/task.json, spawns `claude -p ... <prompt>` as a subprocess,
streams its JSONL events through the shared ClaudeCodeEventParser, emits
conversation.jsonl per turn, writes result.json atomically.
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

from agent.claude_code.event_parser import ClaudeCodeEventParser
from utils.json_io import write_json_atomic

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


def _build_claude_command(task: dict[str, Any]) -> list[str]:
    """claude -p command line from task fields.

    Maps:
      task.model -> --model <id> (defaults to "sonnet" when unset).
      task.reasoning_effort -> --effort <level> (skip when null).
        Net-new wiring; today's claude_code_cli_provider hardcodes no --effort.
      task.prompt -> trailing positional arg.
    """
    cmd = [
        "stdbuf",
        "-oL",
        "-eL",
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        task.get("model") or "sonnet",
        "--add-dir",
        "/",
        "--no-session-persistence",
    ]
    if task.get("reasoning_effort") is not None:
        cmd.extend(["--effort", task["reasoning_effort"]])
    cmd.append(task["prompt"])
    return cmd


def _emit_conversation_turns(task: dict[str, Any], parser: ClaudeCodeEventParser) -> None:
    """Materialize parser.conversation_events to conversation.jsonl."""
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
                "reasoning_summary": ev.get("reasoning_summary", ""),
                "tool_calls": ev["tool_calls"],
                "observations": [
                    {
                        "tool_call_id": obs.get("tool_use_id", ""),
                        "type": "tool_result",
                        "content": obs.get("content", ""),
                        "truncated": False,
                    }
                    for obs in ev.get("observations", [])
                ],
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

    parser = ClaudeCodeEventParser()
    cmd = _build_claude_command(task)

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
                "turns_taken": parser.result_turns,
                "error_traceback": f"claude subprocess error: {e}",
            },
        )
        return 1

    _emit_conversation_turns(task, parser)

    elapsed = time.time() - start
    status = "completed" if exit_code == 0 else "error"
    # Claude reports tool calls per turn; count is the sum across events.
    tool_call_count = sum(len(e["tool_calls"]) for e in parser.conversation_events)
    unique_tools = sorted({
        tc["name"]
        for e in parser.conversation_events
        for tc in e["tool_calls"]
    })
    result: dict[str, Any] = {
        "status": status,
        "turns_taken": parser.result_turns or len(parser.conversation_events),
        "cost_usd": parser.result_cost or 0,
        "model": task.get("model", ""),
        "final_message": parser.final_output,
        "tool_call_count": tool_call_count,
        "unique_tools": unique_tools,
        "token_totals": (parser.result_payload or {}).get("usage", {}),
        "exit_code": exit_code,
    }
    if status == "error":
        result["error_traceback"] = (
            f"claude exit_code={exit_code}, elapsed={elapsed:.1f}s"
        )

    write_json_atomic(result_path, result)
    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
