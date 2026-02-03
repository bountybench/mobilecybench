import json
import os
import tempfile
from unittest.mock import Mock, patch

import pytest


def pytest_configure(config):
    """Set up test environment before any tests run.

    Redirects logs to a temp directory to avoid polluting the project logs folder.
    """
    # Create a temp directory for test logs
    test_logs_dir = tempfile.mkdtemp(prefix="pytest_logs_")
    os.environ["MOBILECYBENCH_LOGS_DIR"] = test_logs_dir
    # Set a fixed session ID to avoid timestamp-based folder creation
    os.environ["MOBILECYBENCH_SESSION_ID"] = "pytest_session"


def pytest_addoption(parser):
    parser.addoption("--dirs", nargs="+", help="Directories to test", required=False)


def create_chat_completion_response(content: str, tool_calls=None):
    """Create a mock ChatCompletion response matching LiteLLM/OpenAI format."""
    response = Mock()

    # Create message object
    message = Mock()
    message.content = content
    message.tool_calls = tool_calls or []

    # Create choice object
    choice = Mock()
    choice.message = message

    # Set up choices list
    response.choices = [choice]

    # Set up usage
    usage = Mock()
    usage.prompt_tokens = 100
    usage.completion_tokens = 50
    usage.total_tokens = 150
    response.usage = usage

    # Set response id
    response.id = "test-response-id"

    return response


class MockModelProvider:
    """Mock implementation of ModelProvider for testing."""

    def __init__(self):
        # Make call a Mock so we can track call_count
        self.call = Mock(side_effect=self._mock_call)

    def validate(self, model: str = None):
        """Mock validate method."""
        pass

    def _mock_call(self, **kwargs):
        """Mock call method that returns a ChatCompletion response."""
        return create_chat_completion_response(
            content=json.dumps({"command": "ActionCommand", "action": "ls"})
        )


@pytest.fixture
def mock_model_provider():
    """Fixture that provides a mock model provider."""
    return MockModelProvider()


@pytest.fixture
def mock_agent_dependencies(mock_model_provider):
    """Fixture that patches all external dependencies for CustomAgent."""
    with patch(
        "agent.custom_agent.get_model_provider", return_value=mock_model_provider
    ):
        with patch("agent.custom_agent.TokenTracker") as mock_tracker:
            with patch("agent.custom_agent.agent_logger"):
                with patch("agent.custom_agent.logger_manager") as mock_logger_mgr:
                    mock_logger_mgr.get_log_file_name.return_value = "test_agent.log"
                    mock_tracker_instance = Mock()
                    mock_tracker_instance.record_from_openai_response = Mock()
                    mock_tracker_instance.totals = Mock(
                        return_value={"input_tokens": 100, "output_tokens": 50}
                    )
                    mock_tracker.return_value = mock_tracker_instance
                    yield {
                        "provider": mock_model_provider,
                        "tracker": mock_tracker_instance,
                    }
