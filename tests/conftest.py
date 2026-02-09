import json
import os
import tempfile
from unittest.mock import Mock, patch

import pytest

from agent.model_providers.base import FunctionCall, ProviderResponse


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


def create_provider_response(
    content: str = "", function_calls=None, response_id="test-response-id"
) -> ProviderResponse:
    """Create a ProviderResponse for testing.

    Args:
        content: Text content for the assistant message.
        function_calls: Optional list of dicts with keys: name, arguments, call_id.
        response_id: Response ID for conversation continuity.
    """
    fc_list = []
    if function_calls:
        for fc in function_calls:
            fc_list.append(
                FunctionCall(
                    name=fc["name"],
                    arguments=fc.get("arguments", "{}"),
                    call_id=fc.get("call_id", "call_test_123"),
                )
            )

    # Create a mock raw_response for TokenTracker compatibility
    raw_response = Mock()
    raw_response.id = response_id
    usage = Mock()
    usage.input_tokens = 100
    usage.output_tokens = 50
    usage.total_tokens = 150
    raw_response.usage = usage

    return ProviderResponse(
        response_id=response_id,
        assistant_text=content,
        function_calls=fc_list,
        raw_response=raw_response,
    )


class MockModelProvider:
    """Mock implementation of ModelProvider for testing.

    Uses the same ``_record_history()`` / ``get_conversation_history()``
    helpers from the real base class to keep the history format in sync.
    """

    def __init__(self):
        # Shared history list (same as ModelProvider base)
        self._conversation_history = []
        # Make call a Mock so we can track call_count
        self.call = Mock(side_effect=self._mock_call)

    def setup(self, **kwargs):
        pass

    def _mock_call(self, **kwargs):
        """Mock call method that returns a ProviderResponse."""
        resp = create_provider_response(
            content=json.dumps({"command": "ActionCommand", "action": "ls"})
        )
        # Reuse the base-class helper logic (inlined here since we don't
        # inherit ModelProvider to avoid ABC enforcement in tests).
        self._conversation_history.append(
            {
                "turn": len(self._conversation_history) + 1,
                "response_id": resp.response_id,
                "assistant_text": resp.assistant_text,
                "reasoning_summary": resp.reasoning_summary,
                "function_calls": [
                    {
                        "name": fc.name,
                        "call_id": fc.call_id,
                        "arguments": fc.arguments,
                    }
                    for fc in resp.function_calls
                ],
            }
        )
        return resp

    def get_conversation_history(self):
        return list(self._conversation_history)


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
