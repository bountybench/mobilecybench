from unittest.mock import MagicMock, patch

import pytest

from runner import MobileCybenchRunner


@pytest.fixture
def mock_config():
    """Mock configuration for MobileCybenchRunner"""
    return {
        "server_access": True,
        "build_type": "source",
        "adb_access": "full",
        "max_iterations": 10,
        "max_kali_message_tokens": 1000,
        "max_model_response_tokens": 1000,
        "max_context_length": 10000,
        "model": "gpt-4",
        "screenshot_mode": False,
        "headless_mode": True,
        "dry_run": True,
        "agent_image": "test-image",
    }


@pytest.fixture
def runner(mock_config):
    """Create a MobileCybenchRunner instance for testing"""
    with patch("runner.Path.exists", return_value=True), patch(
        "runner.get_app_metadata"
    ) as mock_metadata:
        mock_metadata.return_value = {"app_name": "test_app"}
        runner_instance = MobileCybenchRunner(
            app_name="test_app", config=mock_config, agent_only=True
        )
        return runner_instance


##########################################
#     MCP Server Validation Tests       #
##########################################


@patch("runner.MCPToolExecutor")
def test_validate_mcp_server_success(mock_executor_class, runner):
    """Test successful MCP server validation with codebase directory found"""
    mock_executor = MagicMock()
    mock_executor_class.return_value = mock_executor

    mock_executor.call_tool.return_value = {
        "result": {"structuredContent": {"response": "codebase\nfile1.txt\nfile2.txt"}}
    }

    runner._validate_mcp_server()

    mock_executor.call_tool.assert_called_once_with(
        "execute_command", "ls /app", experiment_id="test_app"
    )


@patch("runner.MCPToolExecutor")
def test_validate_mcp_server_failure(mock_executor_class, runner):
    """Test MCP server validation fails when codebase directory is not found"""
    mock_executor = MagicMock()
    mock_executor_class.return_value = mock_executor

    mock_executor.call_tool.return_value = {
        "result": {"structuredContent": {"response": "file1.txt\nfile2.txt\nother_dir"}}
    }

    with pytest.raises(SystemExit):
        runner._validate_mcp_server()
