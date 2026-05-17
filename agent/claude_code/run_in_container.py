"""In-container entrypoint for the claude-code BYO reference image."""

from __future__ import annotations

import sys
from typing import Any

from agent.claude_code.event_parser import ClaudeCodeEventParser
from agent.in_container.paths import TASK_JSON
from agent.in_container.runner import run


def _build_cmd(task: dict[str, Any]) -> list[str]:
    cmd = [
        "stdbuf",
        "-oL",
        "-eL",
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        # Emit stream_event rows incl. message_delta (final per-turn usage +
        # stop_reason). Without this, totals are populated only by the terminal
        # result event — lost on SIGTERM.
        "--include-partial-messages",
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


if __name__ == "__main__":
    sys.exit(
        run(
            sys.argv[1] if len(sys.argv) > 1 else TASK_JSON,
            parser_factory=ClaudeCodeEventParser,
            build_cmd=_build_cmd,
        )
    )
