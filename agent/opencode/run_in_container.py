"""In-container entrypoint for the opencode BYO reference image.

OpenAI auth-source switch (experimental, OpenAI-only):
    OPENCODE_OPENAI_AUTH=auto    (default) strip OPENAI_API_KEY only when
                                 OPENCODE_AUTH_CONTENT is present; otherwise
                                 keep API key. Avoids silent breakage when
                                 only one credential is available.
    OPENCODE_OPENAI_AUTH=oauth   force ChatGPT-OAuth blob; strip OPENAI_API_KEY.
    OPENCODE_OPENAI_AUTH=apikey  force OPENAI_API_KEY; strip OPENCODE_AUTH_CONTENT.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from agent.in_container.paths import TASK_JSON
from agent.in_container.runner import run
from agent.opencode.event_parser import OpencodeEventParser
from utils.logger import logger

# OpenAI auth-source switch. Scope: OpenAI only. Strip the inactive path's
# OpenAI credential so opencode cannot silently swap auth source mid-run.
_OPENAI_AUTH_STRIP = {
    "oauth": ("OPENAI_API_KEY",),
    "apikey": ("OPENCODE_AUTH_CONTENT",),
}


def _build_cmd(task: dict[str, Any]) -> list[str]:
    working_dir = "/app/apk" if task["no_codebase"] else "/app/codebase"
    cmd = [
        "stdbuf",
        "-oL",
        "-eL",
        "opencode",
        "run",
        "--format",
        "json",
        # The container IS the sandbox; bypass per-tool permission prompts.
        "--dangerously-skip-permissions",
        "--dir",
        working_dir,
        "--model",
        task["model"],
    ]
    if task.get("reasoning_effort"):
        cmd.extend(["--variant", task["reasoning_effort"]])
    cmd.append(task["prompt"])
    return cmd


def _normalize_provider_env() -> None:
    """Translate host env names to names opencode's provider SDKs read."""
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        os.environ.setdefault("GOOGLE_GENERATIVE_AI_API_KEY", gemini_key)


def _apply_openai_auth_mode() -> None:
    """Pick opencode's OpenAI auth source (experimental, OpenAI-only).

    Default 'auto' prefers OAuth when its blob is present, else keeps the
    API key — never strips a credential when no alternative is available.
    Explicit 'oauth'/'apikey' force deterministic stripping. Non-OpenAI
    runs are unaffected.
    """
    mode = os.environ.get("OPENCODE_OPENAI_AUTH", "auto")
    if mode == "auto":
        strip = ("OPENAI_API_KEY",) if os.environ.get("OPENCODE_AUTH_CONTENT") else ()
    elif mode in _OPENAI_AUTH_STRIP:
        strip = _OPENAI_AUTH_STRIP[mode]
    else:
        sys.exit(
            f"[opencode] OPENCODE_OPENAI_AUTH={mode!r} "
            f"must be 'auto', 'oauth', or 'apikey'"
        )
    stripped = [k for k in strip if os.environ.pop(k, None)]
    logger.info("opencode openai auth: mode=%s (stripped: %s)", mode, stripped)


if __name__ == "__main__":
    _normalize_provider_env()
    _apply_openai_auth_mode()
    sys.exit(
        run(
            sys.argv[1] if len(sys.argv) > 1 else TASK_JSON,
            parser_factory=OpencodeEventParser,
            build_cmd=_build_cmd,
        )
    )
