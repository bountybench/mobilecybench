"""In-container entrypoint for the claude-code BYO reference image."""

from __future__ import annotations

import sys
from typing import Any

from agent.in_container.runner import run
from agent.claude_code.event_parser import ClaudeCodeEventParser


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
            sys.argv[1] if len(sys.argv) > 1 else "/app/task.json",
            parser_factory=ClaudeCodeEventParser,
            build_cmd=_build_cmd,
        )
    )
