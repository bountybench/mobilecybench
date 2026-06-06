#!/usr/bin/env python3
"""Smoke-test a model integration without going through the full agent loop.

Verifies that:
  1. The configured model resolves through `agent.custom.model_providers.factory`.
  2. The provider's `*_API_KEY` env var is present and usable.
  3. The provider returns a non-error response to a trivial prompt.

Usage:
    python scripts/smoke_test_model.py                          # use runner_config.json:model
    python scripts/smoke_test_model.py --model gpt-5.5          # override
    python scripts/smoke_test_model.py --config foo.json        # alt config

Exit codes:
    0  provider returned a response
    1  configuration / API-key error
    2  provider raised at call time (network, invalid id, 4xx/5xx)

Sample success output (gpt-5.5, OPENAI_API_KEY set):

    smoke-test: model='gpt-5.5' allow_unregistered=False
    smoke-test: provider=OpenAIProvider
    smoke-test: prompt='Reply with the single word "OK". No tools, no JSON, just OK.'

    OK in 2.10s
      response_id     = 'resp_...'
      assistant_text  = 'OK'
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _load_dotenv_if_present() -> None:
    env_file = PROJECT_ROOT / "agent" / ".env"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file, override=False)
    except ImportError:
        # python-dotenv is in requirements.txt; only hit on a partial install.
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _read_model_from_config(config_path: Path) -> tuple[str, bool]:
    """Return (model, allow_unregistered) from runner_config.json."""
    data = json.loads(config_path.read_text())
    return data["model"], bool(
        data.get("allow_unregistered_models_in_custom_mode", False)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        help="Model id to smoke-test (overrides runner_config.json:model).",
    )
    parser.add_argument(
        "--config",
        default="runner_config.json",
        help="Runner config path (default: runner_config.json at repo root).",
    )
    parser.add_argument(
        "--prompt",
        default='Reply with the single word "OK". No tools, no JSON, just OK.',
        help="Prompt to send. Default is a trivial single-token check.",
    )
    parser.add_argument(
        "--allow-unregistered",
        action="store_true",
        help=(
            "Force allow_unregistered_models_in_custom_mode=true regardless "
            "of config."
        ),
    )
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        help="Optional reasoning_effort / variant string forwarded verbatim.",
    )
    args = parser.parse_args()

    _load_dotenv_if_present()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path

    if args.model:
        model = args.model
        allow_unregistered = args.allow_unregistered
    else:
        if not config_path.exists():
            print(
                f"ERROR: --model not given and {config_path} not found.",
                file=sys.stderr,
            )
            return 1
        try:
            model, allow_unregistered = _read_model_from_config(config_path)
        except (OSError, json.JSONDecodeError, KeyError) as e:
            # OSError covers PermissionError / IsADirectoryError on read_text;
            # JSONDecodeError covers malformed config; KeyError covers a
            # config that parses but lacks a "model" key. All three should
            # land on the documented exit-1 path, not a Python traceback.
            print(
                f"ERROR: failed to read model from {config_path}: {e}", file=sys.stderr
            )
            return 1
        if args.allow_unregistered:
            allow_unregistered = True

    print(
        f"smoke-test: model={model!r} allow_unregistered={allow_unregistered}",
        flush=True,
    )

    try:
        from agent.custom.model_providers import get_model_provider
    except ImportError as e:
        print(f"ERROR: cannot import model_providers ({e}).", file=sys.stderr)
        return 1

    try:
        provider = get_model_provider(
            model=model,
            instructions="You are a smoke-test. Reply briefly.",
            tools=None,
            max_output_tokens=64,
            timeout_ms=60_000,
            reasoning_effort=args.reasoning_effort,
            allow_unregistered=allow_unregistered,
        )
    except ValueError as e:
        print(f"ERROR: provider construction failed: {e}", file=sys.stderr)
        return 1

    print(f"smoke-test: provider={type(provider).__name__}")
    print(f"smoke-test: prompt={args.prompt!r}")

    start = time.perf_counter()
    try:
        resp = provider.call(args.prompt)
    except Exception as e:
        elapsed = time.perf_counter() - start
        print(
            f"ERROR: provider.call raised after {elapsed:.2f}s: "
            f"{type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return 2
    elapsed = time.perf_counter() - start

    text = (resp.assistant_text or "").strip()
    reasoning = (resp.reasoning_summary or "").strip()
    tool_calls = resp.function_calls or []

    print()
    print(f"OK in {elapsed:.2f}s")
    print(f"  response_id     = {resp.response_id!r}")
    print(f"  assistant_text  = {text[:200]!r}{'...' if len(text) > 200 else ''}")
    if reasoning:
        print(
            f"  reasoning       = {reasoning[:200]!r}"
            f"{'...' if len(reasoning) > 200 else ''}"
        )
    if tool_calls:
        names = [fc.name for fc in tool_calls]
        print(f"  tool_calls      = {names}")

    if not text and not reasoning and not tool_calls:
        print(
            "WARNING: provider returned an empty response. The model may be "
            "configured incorrectly (e.g. unsupported reasoning settings) "
            "or the API key may lack access.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
