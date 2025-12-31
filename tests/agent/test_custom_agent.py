import json
from unittest.mock import patch

from agent.custom_agent import CustomAgent
from models.config import CustomAgentConfig, EnvironmentConfig, RunnerConfig


class TestCustomAgentMaxIterations:
    """Test suite for CustomAgent max_iterations behavior."""

    def test_max_iterations_respected_when_no_final_submission(
        self, mock_agent_dependencies
    ):
        """Test that agent stops after max_iterations when no final submission is received."""
        max_iterations = 3

        env = EnvironmentConfig(
            build_type="skip-apk",
            server_access=True,
            adb_access="full",
            headless_mode=False,
            docker_mode=False,
            dry_run=False,
            screenshot_mode=False,
        )

        agents = {
            "custom": CustomAgentConfig(
                model="gpt-4o-mini",
                max_iterations=max_iterations,
                max_model_response_tokens=1000,
                max_kali_message_tokens=500,
                max_context_length=10000,
            )
        }

        runner_config = RunnerConfig(environment=env, agents=agents)

        agent = CustomAgent(
            runner_config,
            app_name="test_app",
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
            response = type("MockResponse", (), {})()
            if call_count == stop_at_turn:
                response.output_text = json.dumps(
                    {
                        "command": "FinalSubmissionCommand",
                    }
                )
            else:
                response.output_text = json.dumps(
                    {"command": "ActionCommand", "action": "ls"}
                )
            response.tool_outputs = []
            response.output = []
            return response

        mock_agent_dependencies["provider"].call = mock_call

        env = EnvironmentConfig(
            build_type="skip-apk",
            server_access=True,
            adb_access="full",
            headless_mode=False,
            docker_mode=False,
            dry_run=False,
            screenshot_mode=False,
        )

        agents = {
            "custom": CustomAgentConfig(
                model="gpt-4o-mini",
                max_iterations=max_iterations,
                max_model_response_tokens=1000,
                max_kali_message_tokens=500,
                max_context_length=10000,
            )
        }

        runner_config = RunnerConfig(environment=env, agents=agents)

        agent = CustomAgent(
            runner_config,
            app_name="test_app",
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

        env = EnvironmentConfig(
            build_type="skip-apk",
            server_access=True,
            adb_access="full",
            headless_mode=False,
            docker_mode=False,
            dry_run=False,
            screenshot_mode=False,
        )

        agents = {
            "custom": CustomAgentConfig(
                model="gpt-4o-mini",
                max_iterations=1,
                max_model_response_tokens=1000,
                max_kali_message_tokens=500,
                max_context_length=10000,
            )
        }

        runner_config = RunnerConfig(environment=env, agents=agents)

        agent = CustomAgent(
            runner_config,
            app_name="test_app",
            package_name="com.test.app",
        )

        result = agent.run()

        # Verify exactly one call was made
        assert mock_agent_dependencies["provider"].call.call_count == 1
        assert result["turns"] == 1
        assert result["status"] == "max_iterations_reached"

    def test_dry_run_mode(self, mock_agent_dependencies):
        """Test that dry run mode returns immediately without making API calls."""

        env = EnvironmentConfig(
            build_type="skip-apk",
            server_access=True,
            adb_access="full",
            headless_mode=False,
            docker_mode=False,
            dry_run=True,
            screenshot_mode=False,
        )

        agents = {
            "custom": CustomAgentConfig(
                model="gpt-4o-mini",
                max_iterations=10,
                max_model_response_tokens=1000,
                max_kali_message_tokens=500,
                max_context_length=10000,
            )
        }

        runner_config = RunnerConfig(environment=env, agents=agents)

        agent = CustomAgent(
            runner_config,
            app_name="test_app",
            package_name="com.test.app",
        )

        result = agent.run()

        # Verify no API calls were made
        assert mock_agent_dependencies["provider"].call.call_count == 0

        # Verify dry run result
        assert result["turns"] == 0
        assert "dry run" in result["status"].lower()

    def test_conversation_cleanup_on_max_iterations(self, mock_agent_dependencies):
        """Test that conversation is deleted when max iterations is reached."""

        env = EnvironmentConfig(
            build_type="skip-apk",
            server_access=True,
            adb_access="full",
            headless_mode=False,
            docker_mode=False,
            dry_run=False,
            screenshot_mode=False,
        )

        agents = {
            "custom": CustomAgentConfig(
                model="gpt-4o-mini",
                max_iterations=2,
                max_model_response_tokens=1000,
                max_kali_message_tokens=500,
                max_context_length=10000,
            )
        }

        runner_config = RunnerConfig(environment=env, agents=agents)

        agent = CustomAgent(
            runner_config,
            app_name="test_app",
            package_name="com.test.app",
        )

        agent.run()

        # Verify conversation was deleted
        mock_agent_dependencies[
            "provider"
        ].client.conversations.delete.assert_called_once()
        assert (
            mock_agent_dependencies["provider"].client.conversations.delete.call_args[
                1
            ]["conversation_id"]
            == "test_conv_123"
        )

    def test_conversation_cleanup_on_final_submission(self, mock_agent_dependencies):
        """Test that conversation is deleted when final submission is received."""

        def mock_call(*args, **kwargs):
            response = type("MockResponse", (), {})()
            response.output_text = json.dumps(
                {
                    "command": "FinalSubmissionCommand",
                }
            )
            response.tool_outputs = []
            response.output = []
            return response

        mock_agent_dependencies["provider"].call = mock_call

        env = EnvironmentConfig(
            build_type="skip-apk",
            server_access=True,
            adb_access="full",
            headless_mode=False,
            docker_mode=False,
            dry_run=False,
            screenshot_mode=False,
        )

        agents = {
            "custom": CustomAgentConfig(
                model="gpt-4o-mini",
                max_iterations=10,
                max_model_response_tokens=1000,
                max_kali_message_tokens=500,
                max_context_length=10000,
            )
        }

        runner_config = RunnerConfig(environment=env, agents=agents)

        agent = CustomAgent(
            runner_config,
            app_name="test_app",
            package_name="com.test.app",
        )

        agent.run()

        # Verify conversation was deleted
        mock_agent_dependencies[
            "provider"
        ].client.conversations.delete.assert_called_once()
