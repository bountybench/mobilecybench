"""Tests for scripts/smoke_test_model.py.

The script is the user-facing replacement for the broken `dry_run: true`
smoke-test instruction in ADDING_MODELS.md (R2.22). It must:

  - Read `model` from runner_config.json by default; --model overrides
  - Return exit 0 on a successful provider call
  - Return exit 1 for config / API-key errors (provider construction)
  - Return exit 2 for runtime provider errors (network, 4xx/5xx)
  - Surface a clear error if the response is structurally empty

These are unit tests — the provider call is mocked via
agent.model_providers.factory.get_model_provider so we never hit a real
LLM endpoint.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "smoke_test_model.py"


def _import_script():
    """Import scripts/smoke_test_model.py as a module.

    The script doesn't live under a package, so importlib by path is the
    right way in. Cached on the module to keep test runs fast.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "smoke_test_model_under_test", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def smoke_test_module():
    return _import_script()


def _provider_response(text: str = "OK", reasoning: str = "", tool_calls=None):
    """Build a ProviderResponse-shaped object the script will read."""
    resp = MagicMock()
    resp.response_id = "resp_abc123"
    resp.assistant_text = text
    resp.reasoning_summary = reasoning
    resp.function_calls = tool_calls or []
    return resp


def _run_main(module, argv: list[str]) -> int:
    """Invoke main() with a synthetic argv and return its exit code."""
    with patch.object(sys, "argv", ["smoke_test_model.py", *argv]):
        return module.main()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_main_returns_0_on_successful_call(smoke_test_module, tmp_path):
    """A provider that returns a non-empty assistant_text → exit 0."""
    config = {
        "model": "gpt-5.5",
        "build_type": "skip-apk",
        "agent_image": "x:latest",
        "server_access": True,
        "adb_access": "full",
        "max_iterations": 1,
        "max_model_response_tokens": 64,
        "screenshot_mode": False,
        "dry_run": False,
        "workflow": "exploit",
        "synthetic_vuln_id": "vuln_0",
    }
    config_path = tmp_path / "runner_config.json"
    config_path.write_text(json.dumps(config))

    fake_provider = MagicMock()
    fake_provider.call.return_value = _provider_response(text="OK")

    with patch(
        "agent.model_providers.get_model_provider", return_value=fake_provider
    ) as mock_factory:
        rc = _run_main(smoke_test_module, ["--config", str(config_path)])

    assert rc == 0
    # Factory was called with the config's model.
    assert mock_factory.call_args.kwargs["model"] == "gpt-5.5"
    fake_provider.call.assert_called_once()


def test_main_uses_explicit_model_override(smoke_test_module):
    """--model on the CLI overrides runner_config.json:model."""
    fake_provider = MagicMock()
    fake_provider.call.return_value = _provider_response(text="OK")

    with patch(
        "agent.model_providers.get_model_provider", return_value=fake_provider
    ) as mock_factory:
        # No --config; we override model inline.
        rc = _run_main(smoke_test_module, ["--model", "claude-opus-4-7"])

    assert rc == 0
    assert mock_factory.call_args.kwargs["model"] == "claude-opus-4-7"


# ---------------------------------------------------------------------------
# Config / API-key errors → exit 1
# ---------------------------------------------------------------------------


def test_main_returns_1_on_missing_config(smoke_test_module, tmp_path):
    """No --model and config_path doesn't exist → exit 1."""
    rc = _run_main(
        smoke_test_module, ["--config", str(tmp_path / "does-not-exist.json")]
    )
    assert rc == 1


def test_main_returns_1_on_malformed_config(smoke_test_module, tmp_path):
    """Config file exists but is invalid JSON → exit 1."""
    bad = tmp_path / "broken.json"
    bad.write_text("{ this is not json")
    rc = _run_main(smoke_test_module, ["--config", str(bad)])
    assert rc == 1


def test_main_returns_1_on_missing_model_key(smoke_test_module, tmp_path):
    """Config file exists, valid JSON, but no `model` key → exit 1."""
    cfg = tmp_path / "no-model.json"
    cfg.write_text(json.dumps({"workflow": "exploit"}))
    rc = _run_main(smoke_test_module, ["--config", str(cfg)])
    assert rc == 1


def test_main_returns_1_when_config_path_is_a_directory(smoke_test_module, tmp_path):
    """`--config <dir>` → read_text raises IsADirectoryError → exit 1, not a traceback."""
    rc = _run_main(smoke_test_module, ["--config", str(tmp_path)])
    assert rc == 1


def test_main_returns_1_on_provider_construction_error(smoke_test_module):
    """get_model_provider raising ValueError (unsupported model / missing key) → exit 1."""
    with patch(
        "agent.model_providers.get_model_provider",
        side_effect=ValueError("Unsupported model: 'totally-fake'"),
    ):
        rc = _run_main(smoke_test_module, ["--model", "totally-fake"])
    assert rc == 1


# ---------------------------------------------------------------------------
# Runtime provider errors → exit 2
# ---------------------------------------------------------------------------


def test_main_returns_2_on_provider_call_runtime_error(smoke_test_module):
    """Provider constructed OK but .call() raises (network / API error) → exit 2."""
    fake_provider = MagicMock()
    fake_provider.call.side_effect = ConnectionError("backend unreachable")

    with patch("agent.model_providers.get_model_provider", return_value=fake_provider):
        rc = _run_main(smoke_test_module, ["--model", "gpt-5.5"])
    assert rc == 2


def test_main_returns_2_on_empty_response(smoke_test_module):
    """Provider returns no text, no reasoning, no tool calls → treat as broken."""
    fake_provider = MagicMock()
    fake_provider.call.return_value = _provider_response(
        text="", reasoning="", tool_calls=[]
    )

    with patch("agent.model_providers.get_model_provider", return_value=fake_provider):
        rc = _run_main(smoke_test_module, ["--model", "gpt-5.5"])
    assert rc == 2


def test_main_accepts_response_with_only_reasoning(smoke_test_module):
    """A response with reasoning_summary but no assistant_text is valid (thinking-only models)."""
    fake_provider = MagicMock()
    fake_provider.call.return_value = _provider_response(
        text="", reasoning="thinking through the problem"
    )

    with patch("agent.model_providers.get_model_provider", return_value=fake_provider):
        rc = _run_main(smoke_test_module, ["--model", "gpt-5.5"])
    assert rc == 0


def test_main_accepts_response_with_only_tool_calls(smoke_test_module):
    """A response with tool_calls but no assistant_text is valid (function-calling-only models)."""
    fc = MagicMock()
    fc.name = "execute_command"
    fake_provider = MagicMock()
    fake_provider.call.return_value = _provider_response(text="", tool_calls=[fc])

    with patch("agent.model_providers.get_model_provider", return_value=fake_provider):
        rc = _run_main(smoke_test_module, ["--model", "gpt-5.5"])
    assert rc == 0


# ---------------------------------------------------------------------------
# allow_unregistered flag wiring
# ---------------------------------------------------------------------------


def test_main_propagates_allow_unregistered_from_cli(smoke_test_module):
    """--allow-unregistered forces allow_unregistered=True regardless of config."""
    fake_provider = MagicMock()
    fake_provider.call.return_value = _provider_response(text="OK")

    with patch(
        "agent.model_providers.get_model_provider", return_value=fake_provider
    ) as mock_factory:
        _run_main(
            smoke_test_module, ["--model", "fake-model-id", "--allow-unregistered"]
        )

    assert mock_factory.call_args.kwargs["allow_unregistered"] is True


def test_main_propagates_allow_unregistered_from_config(smoke_test_module, tmp_path):
    """allow_unregistered_models=true in runner_config.json reaches the factory."""
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"model": "x", "allow_unregistered_models": True}))

    fake_provider = MagicMock()
    fake_provider.call.return_value = _provider_response(text="OK")

    with patch(
        "agent.model_providers.get_model_provider", return_value=fake_provider
    ) as mock_factory:
        _run_main(smoke_test_module, ["--config", str(cfg)])

    assert mock_factory.call_args.kwargs["allow_unregistered"] is True
