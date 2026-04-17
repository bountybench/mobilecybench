"""Tests for runner.py - Workflow-based runner."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from jsonschema import validate

from models.config import RunnerConfig
from runner import create_workflow, main, run
from utils.logger import logger_manager
from workflows import ExploitWorkflow


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
        workflow="exploit",
    )


@pytest.fixture
def exploit_config(base_config):
    """Configuration for exploit workflow."""
    return RunnerConfig(**{**base_config.model_dump(), "workflow": "exploit"})


class TestCreateWorkflow:
    """Tests for workflow selection logic."""

    def test_creates_exploit_workflow_by_default(self, base_config, tmp_path):
        """Default workflow type is ExploitWorkflow."""
        workflow = create_workflow(base_config, "test_app", tmp_path)
        assert isinstance(workflow, ExploitWorkflow)

    def test_creates_exploit_workflow_when_configured(self, exploit_config, tmp_path):
        """ExploitWorkflow is created when config.workflow == 'exploit'."""
        workflow = create_workflow(exploit_config, "test_app", tmp_path)
        assert isinstance(workflow, ExploitWorkflow)

    def test_creates_redteam_workflow_when_configured(self, base_config, tmp_path):
        """RedTeamWorkflow is created when config.workflow == 'redteam'."""
        from workflows import RedTeamWorkflow

        rt_config = RunnerConfig(**{**base_config.model_dump(), "workflow": "redteam"})
        workflow = create_workflow(rt_config, "test_app", tmp_path)
        assert isinstance(workflow, RedTeamWorkflow)

    def test_gold_run_allowed_with_redteam(self, base_config):
        """gold_run=True is valid with workflow='redteam'."""
        config = RunnerConfig(
            **{**base_config.model_dump(), "workflow": "redteam", "gold_run": True}
        )
        assert config.gold_run is True

    def test_gold_report_implies_gold_run(self, base_config):
        """Setting gold_report auto-enables gold_run."""
        config = RunnerConfig(
            **{
                **base_config.model_dump(),
                "workflow": "redteam",
                "gold_report": "report-0",
            }
        )
        assert config.gold_run is True
        assert config.gold_report == "report-0"


class TestRun:
    """Tests for run() - focus on error handling and cleanup guarantees."""

    def test_success_returns_zero(self, base_config, tmp_path):
        """Successful execution returns exit code 0."""
        with patch("runner.ensure_app_submodule"), patch.object(
            ExploitWorkflow, "validate_arguments"
        ), patch.object(ExploitWorkflow, "setup_runtime_environment"), patch.object(
            ExploitWorkflow, "setup_agent"
        ), patch.object(
            ExploitWorkflow, "run_agent", return_value={"status": "completed"}
        ), patch.object(
            ExploitWorkflow, "evaluate", return_value={"score": 1}
        ), patch.object(
            ExploitWorkflow, "cleanup"
        ):

            result = run(base_config, "test_app", tmp_path)
            assert result == 0

    def test_validation_error_returns_one_and_still_cleans_up(
        self, base_config, tmp_path
    ):
        """Validation error returns exit code 1 but cleanup still runs."""
        with patch("runner.ensure_app_submodule"), patch.object(
            ExploitWorkflow,
            "validate_arguments",
            side_effect=ValueError("App directory not found"),
        ), patch.object(ExploitWorkflow, "cleanup") as mock_cleanup:

            result = run(base_config, "test_app", tmp_path)
            assert result == 1
            mock_cleanup.assert_called_once()

    def test_cleanup_called_even_when_agent_crashes(self, base_config, tmp_path):
        """Cleanup is called even when agent fails mid-execution."""
        with patch("runner.ensure_app_submodule"), patch.object(
            ExploitWorkflow, "validate_arguments"
        ), patch.object(ExploitWorkflow, "setup_runtime_environment"), patch.object(
            ExploitWorkflow, "setup_agent"
        ), patch.object(
            ExploitWorkflow, "run_agent", side_effect=Exception("Agent crashed")
        ), patch.object(
            ExploitWorkflow, "cleanup"
        ) as mock_cleanup:

            run(base_config, "test_app", tmp_path)
            mock_cleanup.assert_called_once()

    def test_dry_run_skips_agent_execution(self, base_config, tmp_path):
        """Dry run mode runs interactive shell instead of agent."""
        dry_run_config = RunnerConfig(**{**base_config.model_dump(), "dry_run": True})

        with patch("runner.ensure_app_submodule"), patch.object(
            ExploitWorkflow, "validate_arguments"
        ), patch.object(ExploitWorkflow, "setup_runtime_environment"), patch.object(
            ExploitWorkflow, "setup_agent"
        ) as mock_setup_agent, patch.object(
            ExploitWorkflow, "run_agent"
        ) as mock_run_agent, patch.object(
            ExploitWorkflow, "cleanup"
        ), patch(
            "runner.run_interactive_shell", return_value={"status": "completed"}
        ):

            run(dry_run_config, "test_app", tmp_path)

            mock_setup_agent.assert_not_called()
            mock_run_agent.assert_not_called()

    def test_writes_run_summary_json(self, base_config, tmp_path):
        """Run writes structured run_summary.json with key fields."""
        with patch("runner.ensure_app_submodule"), patch.object(
            ExploitWorkflow, "validate_arguments"
        ), patch.object(ExploitWorkflow, "setup_runtime_environment"), patch.object(
            ExploitWorkflow, "setup_agent"
        ), patch.object(
            ExploitWorkflow,
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
            ExploitWorkflow, "evaluate", return_value={"scores": {"probe_a": 1}}
        ), patch.object(
            ExploitWorkflow, "cleanup"
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
            ExploitWorkflow,
            "validate_arguments",
            side_effect=ValueError("bad app"),
        ), patch.object(ExploitWorkflow, "cleanup"):
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
            ExploitWorkflow, "validate_arguments"
        ), patch.object(ExploitWorkflow, "setup_runtime_environment"), patch.object(
            ExploitWorkflow, "setup_agent"
        ), patch.object(
            ExploitWorkflow,
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
            ExploitWorkflow, "evaluate", return_value={"scores": {"probe_a": 1}}
        ), patch.object(
            ExploitWorkflow, "cleanup"
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


class TestAttackModelConfig:
    """Tests for attack_model configuration."""

    def test_auth_attacker_valid_with_redteam(self, base_config):
        config = RunnerConfig(
            **{
                **base_config.model_dump(),
                "workflow": "redteam",
                "attack_model": "auth_attacker",
            }
        )
        assert config.attack_model == "auth_attacker"

    def test_auth_attacker_rejected_with_exploit(self, base_config):
        with pytest.raises(ValueError, match="requires workflow='redteam'"):
            RunnerConfig(
                **{
                    **base_config.model_dump(),
                    "workflow": "exploit",
                    "attack_model": "auth_attacker",
                }
            )

    def test_malicious_apk_default(self, base_config):
        config = RunnerConfig(**{**base_config.model_dump(), "workflow": "redteam"})
        assert config.attack_model == "malicious_apk"

    def test_invalid_attack_model_rejected(self, base_config):
        with pytest.raises(ValueError):
            RunnerConfig(
                **{
                    **base_config.model_dump(),
                    "workflow": "redteam",
                    "attack_model": "bogus",
                }
            )


class TestGoldReportAttackModelOverride:
    """gold_report's report.json overrides config.attack_model before workflow creation."""

    def test_overrides_attack_model_from_report_json(self, base_config, tmp_path):
        """run() reads attack_model from report.json and overrides config default."""
        # Set up zerodays report with auth_attacker
        report_dir = tmp_path / "zerodays" / "reports" / "testapp" / "report-4"
        report_dir.mkdir(parents=True)
        (report_dir / "report.json").write_text(
            json.dumps({"attack_model": "auth_attacker"})
        )
        (report_dir / "exploit").mkdir()
        (report_dir / "exploit" / "exploit.sh").write_text("#!/bin/bash\nexit 0")

        config = RunnerConfig(
            **{
                **base_config.model_dump(),
                "workflow": "redteam",
                "gold_report": "report-4",
            }
        )
        # Config defaults to malicious_apk
        assert config.attack_model == "malicious_apk"

        # run() should override before creating workflow, then fail at validate
        with patch("runner.ensure_app_submodule"), patch.object(
            __import__("workflows").RedTeamWorkflow, "cleanup"
        ):
            run(config, "testapp", tmp_path)

        # After run(), config.attack_model should be overridden
        assert config.attack_model == "auth_attacker"

    def test_missing_attack_model_in_report_json_fails_gracefully(
        self, base_config, tmp_path
    ):
        """gold_report with missing attack_model produces run_summary and returns 1."""
        report_dir = tmp_path / "zerodays" / "reports" / "testapp" / "report-0"
        report_dir.mkdir(parents=True)
        (report_dir / "report.json").write_text(json.dumps({"title": "no model"}))

        config = RunnerConfig(
            **{
                **base_config.model_dump(),
                "workflow": "redteam",
                "gold_report": "report-0",
            }
        )
        exit_code = run(config, "testapp", tmp_path)
        assert exit_code == 1


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
