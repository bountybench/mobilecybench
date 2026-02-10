import json
import os
from unittest.mock import patch

import pytest

from agent.custom_agent import CustomAgent
from agent.model_providers.factory import SupportedModel, get_model_provider
from agent.model_providers.litellm_provider import LiteLLMProvider
from agent.model_providers.openai_provider import OpenAIProvider
from tests.conftest import create_provider_response


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
            max_kali_message_tokens=500,
            max_context_length=10000,
            screenshot_enabled=False,
            app_name="test_app",
            package_name="com.test.app",
        )

        result = agent.run()

        # Verify that the agent made exactly max_iterations calls
        assert mock_agent_dependencies["provider"].call.call_count == max_iterations

        # Verify the result
        assert result["turns_taken"] == max_iterations
        assert result["max_turns"] == max_iterations
        assert result["final_message"] is None

    @patch("agent.custom_agent.subprocess.run")
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
            max_kali_message_tokens=500,
            max_context_length=10000,
            screenshot_enabled=False,
            app_name="test_app",
            package_name="com.test.app",
        )

        result = agent.run()

        # Verify that agent stopped at turn 3, not 10
        assert result["turns_taken"] == stop_at_turn
        assert result["exploit_exists"] is True
        # Parse the final_message to check for command
        final_message_parsed = json.loads(result["final_message"])
        assert final_message_parsed["command"] == "FinalSubmissionCommand"

    def test_single_iteration(self, mock_agent_dependencies):
        """Test agent with max_iterations=1."""
        agent = CustomAgent(
            model="gpt-5.2",
            max_iterations=1,
            max_model_response_tokens=1000,
            max_kali_message_tokens=500,
            max_context_length=10000,
            screenshot_enabled=False,
            app_name="test_app",
            package_name="com.test.app",
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
            max_kali_message_tokens=500,
            max_context_length=10000,
            screenshot_enabled=False,
            app_name="test_app",
            package_name="com.test.app",
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


class TestModelProviderRouting:
    """Test that the factory routes models to the correct provider via SupportedModel enum."""

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_openai_models_use_openai_provider(self):
        for model in [
            SupportedModel.GPT_5_2,
            SupportedModel.GPT_5_2_PRO,
            SupportedModel.GPT_5_2_CODEX,
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

    def test_unsupported_model_raises_error(self):
        with pytest.raises(ValueError, match="Unsupported model"):
            get_model_provider("some-random-model", instructions="test")


class TestCustomAgentWithClaude:
    """Test CustomAgent behavior with claude-opus-4-6."""

    def test_max_iterations_with_claude(self, mock_agent_dependencies):
        max_iterations = 3
        agent = CustomAgent(
            model="claude-opus-4-6",
            max_iterations=max_iterations,
            max_model_response_tokens=1000,
            max_kali_message_tokens=500,
            max_context_length=10000,
            screenshot_enabled=False,
            app_name="test_app",
            package_name="com.test.app",
        )

        result = agent.run()

        assert mock_agent_dependencies["provider"].call.call_count == max_iterations
        assert result["turns_taken"] == max_iterations
        assert result["max_turns"] == max_iterations

    @patch("agent.custom_agent.subprocess.run")
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
            max_kali_message_tokens=500,
            max_context_length=10000,
            screenshot_enabled=False,
            app_name="test_app",
            package_name="com.test.app",
        )

        result = agent.run()

        assert result["turns_taken"] == 2
        assert result["exploit_exists"] is True

    def test_conversation_log_grows_with_claude(self, mock_agent_dependencies):
        agent = CustomAgent(
            model="claude-opus-4-6",
            max_iterations=3,
            max_model_response_tokens=1000,
            max_kali_message_tokens=500,
            max_context_length=10000,
            screenshot_enabled=False,
            app_name="test_app",
            package_name="com.test.app",
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
            max_kali_message_tokens=500,
            max_context_length=10000,
            screenshot_enabled=False,
            app_name="test_app",
            package_name="com.test.app",
        )

        result = agent.run()

        assert mock_agent_dependencies["provider"].call.call_count == max_iterations
        assert result["turns_taken"] == max_iterations
        assert result["max_turns"] == max_iterations

    @patch("agent.custom_agent.subprocess.run")
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
            max_kali_message_tokens=500,
            max_context_length=10000,
            screenshot_enabled=False,
            app_name="test_app",
            package_name="com.test.app",
        )

        result = agent.run()

        assert result["turns_taken"] == 2
        assert result["exploit_exists"] is True

    def test_conversation_log_grows_with_gemini(self, mock_agent_dependencies):
        agent = CustomAgent(
            model="gemini-3-pro-preview",
            max_iterations=3,
            max_model_response_tokens=1000,
            max_kali_message_tokens=500,
            max_context_length=10000,
            screenshot_enabled=False,
            app_name="test_app",
            package_name="com.test.app",
        )

        agent.run()

        history = agent.provider.get_conversation_history()
        assert len(history) == 3
        for i, entry in enumerate(history, 1):
            assert entry["turn"] == i
            assert "response_id" in entry
