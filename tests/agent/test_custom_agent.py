import json
from unittest.mock import patch

from agent.custom_agent import CustomAgent
from tests.conftest import create_chat_completion_response


class TestCustomAgentMaxIterations:
    """Test suite for CustomAgent max_iterations behavior."""

    def test_max_iterations_respected_when_no_final_submission(
        self, mock_agent_dependencies
    ):
        """Test that agent stops after max_iterations when no final submission is received."""
        max_iterations = 3

        agent = CustomAgent(
            model="gpt-4o-mini",
            max_iterations=max_iterations,
            max_model_response_tokens=1000,
            max_kali_message_tokens=500,
            max_context_length=10000,
            screenshot_enabled=False,
            app_name="test_app",
            dry_run=False,
            package_name="com.test.app",
        )

        result = agent.run()

        # Verify that the agent made exactly max_iterations calls
        assert mock_agent_dependencies["provider"].call.call_count == max_iterations

        # Verify the result status and turns
        assert result["status"] == "max_iterations_reached"
        assert result["turns"] == max_iterations
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
                return create_chat_completion_response(
                    content=json.dumps({"command": "FinalSubmissionCommand"})
                )
            else:
                return create_chat_completion_response(
                    content=json.dumps({"command": "ActionCommand", "action": "ls"})
                )

        mock_agent_dependencies["provider"].call = mock_call

        agent = CustomAgent(
            model="gpt-4o-mini",
            max_iterations=max_iterations,
            max_model_response_tokens=1000,
            max_kali_message_tokens=500,
            max_context_length=10000,
            screenshot_enabled=False,
            app_name="test_app",
            dry_run=False,
            package_name="com.test.app",
        )

        result = agent.run()

        # Verify that agent stopped at turn 3, not 10
        assert result["status"] == "completed"
        assert result["turns"] == stop_at_turn
        # Parse the final_message to check for command
        final_message_parsed = json.loads(result["final_message"])
        assert final_message_parsed["command"] == "FinalSubmissionCommand"

    def test_single_iteration(self, mock_agent_dependencies):
        """Test agent with max_iterations=1."""
        agent = CustomAgent(
            model="gpt-4o-mini",
            max_iterations=1,
            max_model_response_tokens=1000,
            max_kali_message_tokens=500,
            max_context_length=10000,
            screenshot_enabled=False,
            app_name="test_app",
            dry_run=False,
            package_name="com.test.app",
        )

        result = agent.run()

        # Verify exactly one call was made
        assert mock_agent_dependencies["provider"].call.call_count == 1
        assert result["turns"] == 1
        assert result["status"] == "max_iterations_reached"

    def test_dry_run_mode(self, mock_agent_dependencies):
        """Test that dry run mode returns immediately without making API calls."""
        agent = CustomAgent(
            model="gpt-4o-mini",
            max_iterations=10,
            max_model_response_tokens=1000,
            max_kali_message_tokens=500,
            max_context_length=10000,
            screenshot_enabled=False,
            app_name="test_app",
            dry_run=True,
            package_name="com.test.app",
        )

        result = agent.run()

        # Verify no API calls were made
        assert mock_agent_dependencies["provider"].call.call_count == 0

        # Verify dry run result
        assert result["turns"] == 0
        assert "dry run" in result["status"].lower()

    def test_message_history_grows(self, mock_agent_dependencies):
        """Test that message history accumulates across turns."""
        agent = CustomAgent(
            model="gpt-4o-mini",
            max_iterations=3,
            max_model_response_tokens=1000,
            max_kali_message_tokens=500,
            max_context_length=10000,
            screenshot_enabled=False,
            app_name="test_app",
            dry_run=False,
            package_name="com.test.app",
        )

        # Should start with just the system message
        assert len(agent.messages) == 1
        assert agent.messages[0]["role"] == "system"

        agent.run()

        # After run, should have system + assistant messages for each turn
        # Plus warning messages since there were no tool calls
        assert len(agent.messages) > 1
        # Check we have assistant messages
        assistant_messages = [m for m in agent.messages if m["role"] == "assistant"]
        assert len(assistant_messages) >= 1
