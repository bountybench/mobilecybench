import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from jsonschema import validate

from agent.custom.agent import CustomAgent
from agent.custom.model_providers.factory import SupportedModel, get_model_provider
from agent.custom.model_providers.litellm_provider import LiteLLMProvider
from agent.custom.model_providers.openai_provider import OpenAIProvider
from tests.conftest import create_provider_response
from utils.token_tracker import TokenTracker


def _load_conversation_turn_schema() -> dict:
    schema_path = (
        Path(__file__).parent.parent.parent
        / "schemas"
        / "conversation_turn.schema.json"
    )
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_custom_agent_resolves_conversation_schema_from_repo_root() -> None:
    """Regression: CustomAgent._load_conversation_schema must reach the repo
    root and produce a working validator. A stale .parent×2 stopped at agent/
    (no schemas/ there) and produced a no-op validator; malformed conversation
    rows leaked through unchecked."""
    validator = CustomAgent._load_conversation_schema(None)  # self unused
    # Spot-check the validator actually validates: empty dict must fail.
    import jsonschema
    with pytest.raises(jsonschema.ValidationError):
        validator.validate({})


class TestCustomAgentMaxIterations:
    """Test suite for CustomAgent max_iterations behavior."""

    def test_max_iterations_respected_when_no_final_submission(
        self, mock_agent_dependencies
    ):
        """Test that agent stops after max_iterations when no final submission is received."""
        max_iterations = 3

        agent = CustomAgent(
            model="gpt-5.2",
            max_iterations=max_iterations,
            max_model_response_tokens=1000,
            screenshot_enabled=False,
            app_name="test_app",
            instructions="System prompt for com.test.app — test scaffold.",
        )

        result = agent.run()

        # Verify that the agent made exactly max_iterations calls
        assert mock_agent_dependencies["provider"].call.call_count == max_iterations

        # Verify the result
        assert result["turns_taken"] == max_iterations
        assert result["max_turns"] == max_iterations
        assert result["final_message"] is None

    @patch("agent.custom.agent.subprocess.run")
    def test_early_stop_on_final_submission(
        self, mock_subprocess_run, mock_agent_dependencies
    ):
        """Test that agent stops early when FinalSubmissionCommand is received."""
        max_iterations = 10
        stop_at_turn = 3

        # Mock the exploit check to return success (exploit.sh exists)
        mock_subprocess_run.return_value = type(
            "MockResult", (), {"returncode": 0, "stdout": "", "stderr": ""}
        )()

        # Create a provider that returns FinalSubmissionCommand on the 3rd call
        call_count = 0

        def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == stop_at_turn:
                return create_provider_response(
                    content=json.dumps({"command": "FinalSubmissionCommand"}),
                    response_id=f"resp-{call_count}",
                )
            else:
                return create_provider_response(
                    content=json.dumps({"command": "ActionCommand", "action": "ls"}),
                    response_id=f"resp-{call_count}",
                )

        mock_agent_dependencies["provider"].call = mock_call

        agent = CustomAgent(
            model="gpt-5.2",
            max_iterations=max_iterations,
            max_model_response_tokens=1000,
            screenshot_enabled=False,
            app_name="test_app",
            instructions="System prompt for com.test.app — test scaffold.",
        )

        result = agent.run()

        # Verify that agent stopped at turn 3, not 10
        assert result["turns_taken"] == stop_at_turn
        assert result["exploit_exists"] is True
        # Parse the final_message to check for command
        final_message_parsed = json.loads(result["final_message"])
        assert final_message_parsed["command"] == "FinalSubmissionCommand"

    def _exploit_check_agent(self):
        return CustomAgent(
            model="gpt-5.2",
            max_iterations=1,
            max_model_response_tokens=1000,
            screenshot_enabled=False,
            app_name="test_app",
            instructions="System prompt for com.test.app — test scaffold.",
        )

    def test_check_exploit_exists_silent_when_artifact_absent(
        self, mock_agent_dependencies, caplog
    ):
        """A legitimately missing artifact (`test -f` exit 1, empty stderr) is
        the normal "no" answer to an existence check. It must return False
        without emitting any ERROR record — otherwise healthy runs gain a
        false entry in errors.log / ERROR SUMMARY."""
        from agent.custom import agent as ca_mod

        agent = self._exploit_check_agent()
        absent = type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()

        ca_mod.agent_logger.reset_mock()
        with caplog.at_level("ERROR"):
            with patch("subprocess.run", return_value=absent):
                assert agent._check_exploit_exists() is False

        assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
        assert not ca_mod.agent_logger.warning.called

    def test_check_exploit_exists_warns_on_operational_failure(
        self, mock_agent_dependencies
    ):
        """An infra failure (`docker exec` non-zero with stderr) must surface
        as an agent-logger warning so triage can distinguish it from a
        legitimately missing artifact, even though the function still
        returns False either way."""
        from agent.custom import agent as ca_mod

        agent = self._exploit_check_agent()
        infra_fail = type(
            "R",
            (),
            {
                "returncode": 1,
                "stdout": "",
                "stderr": "Error response from daemon: No such container: kali-container",
            },
        )()

        ca_mod.agent_logger.reset_mock()
        with patch("subprocess.run", return_value=infra_fail):
            assert agent._check_exploit_exists() is False

        assert ca_mod.agent_logger.warning.called

    def test_single_iteration(self, mock_agent_dependencies):
        """Test agent with max_iterations=1."""
        agent = CustomAgent(
            model="gpt-5.2",
            max_iterations=1,
            max_model_response_tokens=1000,
            screenshot_enabled=False,
            app_name="test_app",
            instructions="System prompt for com.test.app — test scaffold.",
        )

        result = agent.run()

        # Verify exactly one call was made
        assert mock_agent_dependencies["provider"].call.call_count == 1
        assert result["turns_taken"] == 1
        assert result["max_turns"] == 1

    def test_conversation_log_grows(self, mock_agent_dependencies):
        """Test that conversation log accumulates across turns."""
        agent = CustomAgent(
            model="gpt-5.2",
            max_iterations=3,
            max_model_response_tokens=1000,
            screenshot_enabled=False,
            app_name="test_app",
            instructions="System prompt for com.test.app — test scaffold.",
        )

        # Conversation history should start empty
        assert len(agent.provider.get_conversation_history()) == 0

        agent.run()

        # After run, should have entries for each turn
        history = agent.provider.get_conversation_history()
        assert len(history) == 3
        # Each entry should have a turn number and response_id
        for i, entry in enumerate(history, 1):
            assert entry["turn"] == i
            assert "response_id" in entry

    def test_writes_conversation_jsonl_turn_events(self, mock_agent_dependencies):
        """Agent writes machine-readable per-turn conversation JSONL."""
        long_result = "x" * (CustomAgent.OBSERVATION_MAX_CHARS + 128)

        def mock_call(*args, **kwargs):
            return create_provider_response(
                content=json.dumps({"command": "ActionCommand", "action": "id"}),
                function_calls=[
                    {
                        "name": "execute_command",
                        "arguments": '{"command":"id"}',
                        "call_id": "call_test_1",
                    }
                ],
                response_id="resp-turn-1",
            )

        mock_agent_dependencies["provider"].call = mock_call

        agent = CustomAgent(
            model="gpt-5.2",
            max_iterations=1,
            max_model_response_tokens=1000,
            screenshot_enabled=False,
            app_name="test_app",
            instructions="System prompt for com.test.app — test scaffold.",
        )
        with patch.object(agent.runtime, "execute", return_value=long_result):
            result = agent.run()

        conv_path = (
            mock_agent_dependencies["logs_dir"] / "agent_run" / "conversation.jsonl"
        )
        assert conv_path.exists()
        lines = conv_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        event = json.loads(lines[0])

        assert event["turn_number"] == 1
        assert event["response_id"] == "resp-turn-1"
        assert len(event["tool_calls"]) == 1
        assert event["tool_calls"][0]["name"] == "execute_command"
        assert len(event["observations"]) == 1
        assert event["observations"][0]["type"] == "tool_result"
        assert event["observations"][0]["truncated"] is True
        validate(instance=event, schema=_load_conversation_turn_schema())
        assert result["tool_call_count"] == 1
        assert result["unique_tools"] == ["execute_command"]

    def test_writes_system_prompt_artifact(self, mock_agent_dependencies):
        """Agent persists full system prompt as an artifact for reproducibility."""
        CustomAgent(
            model="gpt-5.2",
            max_iterations=1,
            max_model_response_tokens=1000,
            screenshot_enabled=False,
            app_name="test_app",
            instructions="System prompt for com.test.app — test scaffold.",
        )

        prompt_path = (
            mock_agent_dependencies["logs_dir"] / "agent_run" / "system_prompt.txt"
        )
        assert prompt_path.exists()
        contents = prompt_path.read_text(encoding="utf-8")
        assert contents.strip()
        assert "com.test.app" in contents


class TestModelProviderRouting:
    """Test that the factory routes models to the correct provider via SupportedModel enum."""

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_openai_models_use_openai_provider(self):
        for model in [
            SupportedModel.GPT_5_2,
            SupportedModel.GPT_5_2_PRO,
            SupportedModel.GPT_5_2_CODEX,
            SupportedModel.GPT_5_4,
            SupportedModel.GPT_5_4_PRO,
        ]:
            provider = get_model_provider(model.value.api_id, instructions="test")
            assert isinstance(
                provider, OpenAIProvider
            ), f"{model.value.api_id} should use OpenAIProvider"

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    def test_anthropic_models_use_litellm_provider(self):
        for model in [SupportedModel.CLAUDE_OPUS_4_6, SupportedModel.CLAUDE_SONNET_4_5]:
            provider = get_model_provider(model.value.api_id, instructions="test")
            assert isinstance(
                provider, LiteLLMProvider
            ), f"{model.value.api_id} should use LiteLLMProvider"

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    def test_gemini_models_use_litellm_provider(self):
        for model in [SupportedModel.GEMINI_3_PRO]:
            provider = get_model_provider(model.value.api_id, instructions="test")
            assert isinstance(
                provider, LiteLLMProvider
            ), f"{model.value.api_id} should use LiteLLMProvider"

    def test_unknown_model_blocks_by_default(self):
        """Unknown models are rejected unless allow_unregistered=True.

        Default deny protects cost telemetry: until a model is added to
        SupportedModel and utils/token_pricing.json, cost_usd would read
        as zero. We force operators to opt in explicitly.
        """
        with pytest.raises(ValueError, match="Unsupported model"):
            get_model_provider("some-random-model", instructions="test")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False)
    def test_unknown_model_with_opt_in_routes_to_litellm_with_warning(self, caplog):
        """allow_unregistered=True falls through to LiteLLM with a WARNING.

        Intended for short experiments only; cost telemetry is incorrect
        until the model is registered in token_pricing.json.
        """
        import logging

        with caplog.at_level(logging.WARNING, logger="MobileCyBench"):
            provider = get_model_provider(
                "some-random-model", instructions="test", allow_unregistered=True
            )

        assert isinstance(provider, LiteLLMProvider)
        # The default detection rule (no substring match) routes to OPENAI_API_KEY.
        assert provider._rule.env_var == "OPENAI_API_KEY"
        warning_messages = [r.getMessage() for r in caplog.records]
        assert any(
            "some-random-model" in m and "SupportedModel" in m for m in warning_messages
        ), warning_messages
        # Warning must mention the cost-tracking gap so it isn't silently lost.
        assert any(
            "cost_usd" in m and "$0" in m for m in warning_messages
        ), warning_messages
        assert any(
            "token_pricing.json" in m for m in warning_messages
        ), warning_messages

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=False)
    def test_unknown_claude_model_with_opt_in_auto_detects_anthropic(self, caplog):
        """With opt-in, a substring-recognised model id (e.g. 'claude') routes
        to the matching provider's env var via LiteLLM."""
        import logging

        with caplog.at_level(logging.WARNING, logger="MobileCyBench"):
            provider = get_model_provider(
                "claude-future-model", instructions="test", allow_unregistered=True
            )

        assert isinstance(provider, LiteLLMProvider)
        assert provider._rule.env_var == "ANTHROPIC_API_KEY"
        assert any("claude-future-model" in r.getMessage() for r in caplog.records)


class TestLiteLLMProviderUsagePassthrough:
    """Verify that LiteLLM raw responses flow through to TokenTracker correctly."""

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"})
    @patch("agent.custom.model_providers.litellm_provider.litellm.completion")
    def test_top_level_reasoning_tokens_reach_token_tracker(self, mock_completion):
        usage = SimpleNamespace(
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
            reasoning_tokens=40,
        )
        message = SimpleNamespace(content="ok", reasoning_content="", tool_calls=[])
        choice = SimpleNamespace(message=message)
        mock_completion.return_value = SimpleNamespace(
            id="test-resp-1", choices=[choice], usage=usage
        )

        provider = LiteLLMProvider("claude-opus-4-6", instructions="test")
        resp = provider.call("hello")

        tracker = TokenTracker(jsonl_path="")
        record = tracker.record_from_openai_response(resp.raw_response, model="o3")
        assert record.input_tokens == 200
        assert record.output_tokens == 100
        assert record.reasoning_tokens == 40


class TestCustomAgentWithClaude:
    """Test CustomAgent behavior with claude-opus-4-6."""

    def test_max_iterations_with_claude(self, mock_agent_dependencies):
        max_iterations = 3
        agent = CustomAgent(
            model="claude-opus-4-6",
            max_iterations=max_iterations,
            max_model_response_tokens=1000,
            screenshot_enabled=False,
            app_name="test_app",
            instructions="System prompt for com.test.app — test scaffold.",
        )

        result = agent.run()

        assert mock_agent_dependencies["provider"].call.call_count == max_iterations
        assert result["turns_taken"] == max_iterations
        assert result["max_turns"] == max_iterations

    @patch("agent.custom.agent.subprocess.run")
    def test_early_stop_with_claude(self, mock_subprocess_run, mock_agent_dependencies):
        mock_subprocess_run.return_value = type(
            "MockResult", (), {"returncode": 0, "stdout": "", "stderr": ""}
        )()

        call_count = 0

        def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return create_provider_response(
                    content=json.dumps({"command": "FinalSubmissionCommand"}),
                    response_id=f"litellm_resp-{call_count}",
                )
            return create_provider_response(
                content=json.dumps({"command": "ActionCommand", "action": "ls"}),
                response_id=f"litellm_resp-{call_count}",
            )

        mock_agent_dependencies["provider"].call = mock_call

        agent = CustomAgent(
            model="claude-opus-4-6",
            max_iterations=10,
            max_model_response_tokens=1000,
            screenshot_enabled=False,
            app_name="test_app",
            instructions="System prompt for com.test.app — test scaffold.",
        )

        result = agent.run()

        assert result["turns_taken"] == 2
        assert result["exploit_exists"] is True

    def test_conversation_log_grows_with_claude(self, mock_agent_dependencies):
        agent = CustomAgent(
            model="claude-opus-4-6",
            max_iterations=3,
            max_model_response_tokens=1000,
            screenshot_enabled=False,
            app_name="test_app",
            instructions="System prompt for com.test.app — test scaffold.",
        )

        agent.run()

        history = agent.provider.get_conversation_history()
        assert len(history) == 3
        for i, entry in enumerate(history, 1):
            assert entry["turn"] == i
            assert "response_id" in entry


class TestCustomAgentWithGemini:
    """Test CustomAgent behavior with gemini-3-pro-preview."""

    def test_max_iterations_with_gemini(self, mock_agent_dependencies):
        max_iterations = 3
        agent = CustomAgent(
            model="gemini-3-pro-preview",
            max_iterations=max_iterations,
            max_model_response_tokens=1000,
            screenshot_enabled=False,
            app_name="test_app",
            instructions="System prompt for com.test.app — test scaffold.",
        )

        result = agent.run()

        assert mock_agent_dependencies["provider"].call.call_count == max_iterations
        assert result["turns_taken"] == max_iterations
        assert result["max_turns"] == max_iterations

    @patch("agent.custom.agent.subprocess.run")
    def test_early_stop_with_gemini(self, mock_subprocess_run, mock_agent_dependencies):
        mock_subprocess_run.return_value = type(
            "MockResult", (), {"returncode": 0, "stdout": "", "stderr": ""}
        )()

        call_count = 0

        def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return create_provider_response(
                    content=json.dumps({"command": "FinalSubmissionCommand"}),
                    response_id=f"litellm_resp-{call_count}",
                )
            return create_provider_response(
                content=json.dumps({"command": "ActionCommand", "action": "ls"}),
                response_id=f"litellm_resp-{call_count}",
            )

        mock_agent_dependencies["provider"].call = mock_call

        agent = CustomAgent(
            model="gemini-3-pro-preview",
            max_iterations=10,
            max_model_response_tokens=1000,
            screenshot_enabled=False,
            app_name="test_app",
            instructions="System prompt for com.test.app — test scaffold.",
        )

        result = agent.run()

        assert result["turns_taken"] == 2
        assert result["exploit_exists"] is True

    def test_conversation_log_grows_with_gemini(self, mock_agent_dependencies):
        agent = CustomAgent(
            model="gemini-3-pro-preview",
            max_iterations=3,
            max_model_response_tokens=1000,
            screenshot_enabled=False,
            app_name="test_app",
            instructions="System prompt for com.test.app — test scaffold.",
        )

        agent.run()

        history = agent.provider.get_conversation_history()
        assert len(history) == 3
        for i, entry in enumerate(history, 1):
            assert entry["turn"] == i
            assert "response_id" in entry
