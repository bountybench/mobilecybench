import json
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

# Redirect logs to a temp dir BEFORE importing anything that touches utils.logger.
# The LoggerManager singleton inspects these env vars at construction time, and
# the agent imports below transitively import utils.logger.
os.environ.setdefault("MOBILECYBENCH_LOGS_DIR", tempfile.mkdtemp(prefix="pytest_logs_"))
os.environ.setdefault("MOBILECYBENCH_SESSION_ID", "pytest_session")

import pytest

from agent.custom.model_providers.base import FunctionCall, ProviderResponse


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
    usage.reasoning_tokens = 0
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

    Mirrors the base-class history format (see ModelProvider._record_history).
    """

    def __init__(self, **kwargs):
        self._conversation_history = []
        self.call = Mock(side_effect=self._mock_call)

    def _mock_call(self, *args, **kwargs):
        """Return a ProviderResponse and record history."""
        resp = create_provider_response(
            content=json.dumps({"command": "ActionCommand", "action": "ls"})
        )
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
    logs_dir = Path(tempfile.mkdtemp(prefix="pytest_agent_logs_"))
    with patch(
        "agent.custom.agent.get_model_provider", return_value=mock_model_provider
    ):
        with patch("agent.custom.agent.TokenTracker") as mock_tracker:
            with patch("agent.custom.agent.agent_logger"):
                with patch("agent.custom.agent.logger_manager") as mock_logger_mgr:
                    mock_logger_mgr.get_log_file_name.return_value = "test_agent.log"
                    mock_logger_mgr.get_logs_dir.return_value = logs_dir
                    mock_logger_mgr.get_run_id.return_value = "pytest_session"
                    mock_logger_mgr.get_session_id.return_value = "pytest_session"
                    mock_tracker_instance = Mock()
                    mock_tracker_instance.record_from_openai_response = Mock()
                    mock_tracker_instance.totals = Mock(
                        return_value={
                            "calls": 1,
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "reasoning_tokens": 0,
                            "cache_input_tokens": 0,
                            "cost_usd": 0.0,
                        }
                    )
                    mock_tracker.return_value = mock_tracker_instance
                    yield {
                        "provider": mock_model_provider,
                        "tracker": mock_tracker_instance,
                        "logs_dir": logs_dir,
                    }
