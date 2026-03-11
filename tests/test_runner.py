"""Tests for runner.py - Workflow-based runner."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from jsonschema import validate

from models.config import RunnerConfig
from runner import create_workflow, main, run
from utils.logger import logger_manager
from workflows import DetectionWorkflow, DiscoveryWorkflow, ExploitWorkflow


def _load_run_summary_schema() -> dict:
    schema_path = Path(__file__).parent.parent / "schemas" / "run_summary.schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_conversation_turn_schema() -> dict:
    schema_path = (
        Path(__file__).parent.parent / "schemas" / "conversation_turn.schema.json"
    )
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def base_config():
    """Base configuration for testing."""
    return RunnerConfig(
        server_access=True,
        build_type="source",
        adb_access="full",
        max_iterations=10,
        max_model_response_tokens=1000,
        model="gpt-4",
        screenshot_mode=False,
        dry_run=False,
        agent_image="test-image:latest",
        emulator_display="headed",
        emulator_backend="native",
        workflow="discovery",
    )


@pytest.fixture
def exploit_config(base_config):
    """Configuration for exploit workflow."""
    return RunnerConfig(**{**base_config.model_dump(), "workflow": "exploit"})


class TestCreateWorkflow:
    """Tests for workflow selection logic."""

    def test_creates_discovery_workflow_by_default(self, base_config, tmp_path):
        """Default workflow type is DiscoveryWorkflow."""
        workflow = create_workflow(base_config, "test_app", tmp_path)
        assert isinstance(workflow, DiscoveryWorkflow)

    def test_creates_exploit_workflow_when_configured(self, exploit_config, tmp_path):
        """ExploitWorkflow is created when config.workflow == 'exploit'."""
        workflow = create_workflow(exploit_config, "test_app", tmp_path)
        assert isinstance(workflow, ExploitWorkflow)

    def test_creates_detection_workflow_when_configured(self, base_config, tmp_path):
        """DetectionWorkflow is created when config.workflow == 'detection'."""
        detection_config = RunnerConfig(
            **{**base_config.model_dump(), "workflow": "detection"}
        )
        workflow = create_workflow(detection_config, "test_app", tmp_path)
        assert isinstance(workflow, DetectionWorkflow)


class TestRun:
    """Tests for run() - focus on error handling and cleanup guarantees."""

    def test_success_returns_zero(self, base_config, tmp_path):
        """Successful execution returns exit code 0."""
        with patch("runner.ensure_app_submodule"), patch.object(
            DiscoveryWorkflow, "validate_arguments"
        ), patch.object(DiscoveryWorkflow, "setup_runtime_environment"), patch.object(
            DiscoveryWorkflow, "setup_agent"
        ), patch.object(
            DiscoveryWorkflow, "run_agent", return_value={"status": "completed"}
        ), patch.object(
            DiscoveryWorkflow, "evaluate", return_value={"score": 1}
        ), patch.object(
            DiscoveryWorkflow, "cleanup"
        ):

            result = run(base_config, "test_app", tmp_path)
            assert result == 0

    def test_validation_error_returns_one_and_still_cleans_up(
        self, base_config, tmp_path
    ):
        """Validation error returns exit code 1 but cleanup still runs."""
        with patch("runner.ensure_app_submodule"), patch.object(
            DiscoveryWorkflow,
            "validate_arguments",
            side_effect=ValueError("App directory not found"),
        ), patch.object(DiscoveryWorkflow, "cleanup") as mock_cleanup:

            result = run(base_config, "test_app", tmp_path)
            assert result == 1
            mock_cleanup.assert_called_once()

    def test_cleanup_called_even_when_agent_crashes(self, base_config, tmp_path):
        """Cleanup is called even when agent fails mid-execution."""
        with patch("runner.ensure_app_submodule"), patch.object(
            DiscoveryWorkflow, "validate_arguments"
        ), patch.object(DiscoveryWorkflow, "setup_runtime_environment"), patch.object(
            DiscoveryWorkflow, "setup_agent"
        ), patch.object(
            DiscoveryWorkflow, "run_agent", side_effect=Exception("Agent crashed")
        ), patch.object(
            DiscoveryWorkflow, "cleanup"
        ) as mock_cleanup:

            run(base_config, "test_app", tmp_path)
            mock_cleanup.assert_called_once()

    def test_dry_run_skips_agent_execution(self, base_config, tmp_path):
        """Dry run mode runs interactive shell instead of agent."""
        dry_run_config = RunnerConfig(**{**base_config.model_dump(), "dry_run": True})

        with patch("runner.ensure_app_submodule"), patch.object(
            DiscoveryWorkflow, "validate_arguments"
        ), patch.object(DiscoveryWorkflow, "setup_runtime_environment"), patch.object(
            DiscoveryWorkflow, "setup_agent"
        ) as mock_setup_agent, patch.object(
            DiscoveryWorkflow, "run_agent"
        ) as mock_run_agent, patch.object(
            DiscoveryWorkflow, "cleanup"
        ), patch(
            "runner.run_interactive_shell", return_value={"status": "completed"}
        ):

            run(dry_run_config, "test_app", tmp_path)

            mock_setup_agent.assert_not_called()
            mock_run_agent.assert_not_called()

    def test_writes_run_summary_json(self, base_config, tmp_path):
        """Run writes structured run_summary.json with key fields."""
        with patch("runner.ensure_app_submodule"), patch.object(
            DiscoveryWorkflow, "validate_arguments"
        ), patch.object(DiscoveryWorkflow, "setup_runtime_environment"), patch.object(
            DiscoveryWorkflow, "setup_agent"
        ), patch.object(
            DiscoveryWorkflow,
            "run_agent",
            return_value={
                "status": "completed",
                "turns_taken": 2,
                "tool_call_count": 1,
                "unique_tools": ["execute_command"],
                "token_totals": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cost_usd": 0.1,
                },
                "conversation_file": "logs/experiment_pytest_session/conversation.jsonl",
            },
        ), patch.object(
            DiscoveryWorkflow, "evaluate", return_value={"scores": {"probe_a": 1}}
        ), patch.object(
            DiscoveryWorkflow, "cleanup"
        ):
            result = run(base_config, "test_app", tmp_path)
            assert result == 0

        summary_path = logger_manager.get_logs_dir() / "run_summary.json"
        assert summary_path.exists()

        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)

        assert summary["run_id"]
        assert summary["outcome"] == "success"
        assert summary["context"]["app_name"] == "test_app"
        assert summary["config"]["build_type"] == base_config.build_type
        assert summary["metrics"]["turn_count"] == 2
        assert summary["metrics"]["tool_call_count"] == 1
        assert summary["results"]["scores"] == {"probe_a": 1}
        assert "conversation_jsonl" in summary["artifacts"]
        validate(instance=summary, schema=_load_run_summary_schema())

    def test_writes_run_summary_on_validation_error(self, base_config, tmp_path):
        """Run writes run_summary.json even on validation failure."""
        with patch("runner.ensure_app_submodule"), patch.object(
            DiscoveryWorkflow,
            "validate_arguments",
            side_effect=ValueError("bad app"),
        ), patch.object(DiscoveryWorkflow, "cleanup"):
            result = run(base_config, "test_app", tmp_path)
            assert result == 1

        summary_path = logger_manager.get_logs_dir() / "run_summary.json"
        assert summary_path.exists()
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)
        assert summary["outcome"] == "failure"
        assert summary["exit_reason"] == "validation_error"
        assert summary["artifacts"]["conversation_jsonl"] is None
        validate(instance=summary, schema=_load_run_summary_schema())

    def test_materializes_conversation_jsonl_from_history_fallback(
        self, base_config, tmp_path
    ):
        """Runner creates conversation.jsonl from conversation_history when needed."""
        with patch("runner.ensure_app_submodule"), patch.object(
            DiscoveryWorkflow, "validate_arguments"
        ), patch.object(DiscoveryWorkflow, "setup_runtime_environment"), patch.object(
            DiscoveryWorkflow, "setup_agent"
        ), patch.object(
            DiscoveryWorkflow,
            "run_agent",
            return_value={
                "status": "completed",
                "turns_taken": 1,
                "conversation_history": [
                    {"final_output": "done", "tool_outputs": ["ok"], "turns": 1}
                ],
                "token_totals": {
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost_usd": 0.0,
                },
            },
        ), patch.object(
            DiscoveryWorkflow, "evaluate", return_value={"scores": {"probe_a": 1}}
        ), patch.object(
            DiscoveryWorkflow, "cleanup"
        ):
            result = run(base_config, "test_app", tmp_path)
            assert result == 0

        summary_path = logger_manager.get_logs_dir() / "run_summary.json"
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)

        conversation_rel = summary["artifacts"]["conversation_jsonl"]
        conversation_path = Path(conversation_rel)
        if not conversation_path.is_absolute():
            conversation_path = tmp_path / conversation_path
        assert conversation_path.exists()
        assert summary["context"]["agent_type"] == "codex"
        lines = conversation_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        turn_event = json.loads(lines[0])
        validate(instance=turn_event, schema=_load_conversation_turn_schema())


class TestMain:
    """Tests for CLI entry point."""

    def test_missing_config_file_returns_one(self, tmp_path, monkeypatch):
        """Missing config file returns exit code 1."""
        monkeypatch.chdir(tmp_path)

        with patch(
            "sys.argv", ["runner.py", "test_app", "--config", "nonexistent.json"]
        ):
            result = main()
            assert result == 1
