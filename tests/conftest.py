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


class MockModelProvider:
    """Mock implementation of ModelProvider for testing."""

    def __init__(self):
        self.client = Mock()
        self.client.conversations = Mock()
        self.client.conversations.create = Mock(return_value=Mock(id="test_conv_123"))
        self.client.conversations.delete = Mock()

        # Make call a Mock so we can track call_count
        self.call = Mock(side_effect=self._mock_call)

    def validate(self):
        """Mock validate method."""
        pass

    def _mock_call(self, **kwargs):
        """Mock call method that returns a response with output_text."""
        response = Mock()
        response.output_text = json.dumps({"command": "ActionCommand", "action": "ls"})
        response.tool_outputs = []
        response.tool_calls = []
        response.output = []
        return response


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
