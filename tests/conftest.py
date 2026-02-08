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


def create_responses_api_response(
    content: str, function_calls=None, response_id="test-response-id"
):
    """Create a mock OpenAI Responses API response.

    Args:
        content: Text content for the assistant message.
        function_calls: Optional list of dicts with keys: name, arguments, call_id.
        response_id: Response ID for conversation continuity.
    """
    response = Mock()
    response.id = response_id

    # Build output items
    output_items = []

    # Add message output item if content provided
    if content:
        text_block = Mock()
        text_block.type = "output_text"
        text_block.text = content

        message_item = Mock()
        message_item.type = "message"
        message_item.content = [text_block]
        output_items.append(message_item)

    # Add function_call output items
    if function_calls:
        for fc in function_calls:
            fc_item = Mock()
            fc_item.type = "function_call"
            fc_item.name = fc["name"]
            fc_item.arguments = fc.get("arguments", "{}")
            fc_item.call_id = fc.get("call_id", "call_test_123")
            output_items.append(fc_item)

    response.output = output_items

    # Set up usage
    usage = Mock()
    usage.input_tokens = 100
    usage.output_tokens = 50
    usage.total_tokens = 150
    response.usage = usage

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
        """Mock call method that returns a Responses API response."""
        return create_responses_api_response(
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
