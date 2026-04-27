"""Tests for runner.py - Workflow-based runner."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from jsonschema import validate

from models.config import RunnerConfig
from runner import create_workflow, main, run
from utils.exploit_source import ExploitSource
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
        synthetic_vuln_id="vuln_0",
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

        rt_config = RunnerConfig(
            **{
                **base_config.model_dump(),
                "workflow": "redteam",
                "task": "report-0",
                "synthetic_vuln_id": None,
                "attacker_model": "malicious_app",
            }
        )
        workflow = create_workflow(rt_config, "test_app", tmp_path)
        assert isinstance(workflow, RedTeamWorkflow)

    def test_gold_run_allowed_with_redteam(self, base_config):
        """gold_run=True is valid with workflow='redteam'."""
        config = RunnerConfig(
            **{
                **base_config.model_dump(),
                "workflow": "redteam",
                "task": "report-0",
                "synthetic_vuln_id": None,
                "gold_run": True,
            }
        )
        assert config.gold_run is True

    def test_redteam_requires_task(self, base_config):
        """workflow='redteam' without task or synthetic_vuln_id raises ValueError."""
        with pytest.raises(ValueError, match="exactly one"):
            RunnerConfig(
                **{
                    **base_config.model_dump(),
                    "workflow": "redteam",
                    "synthetic_vuln_id": None,
                }
            )


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
        # cost_usd is sourced from token_totals when run_result has no
        # top-level cost (the custom + codex agent shape).
        assert summary["metrics"]["cost_usd"] == 0.1
        assert summary["metrics"]["token_totals"]["cost_usd"] == 0.1
        assert summary["results"]["scores"] == {"probe_a": 1}
        assert "conversation_jsonl" in summary["artifacts"]
        validate(instance=summary, schema=_load_run_summary_schema())

    def test_run_summary_cost_usd_prefers_top_level(self, base_config, tmp_path):
        """When run_result reports top-level cost_usd (claude-code path),
        run_summary surfaces that value instead of the nested one."""
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
                "tool_call_count": 0,
                "unique_tools": [],
                "cost_usd": 0.42,  # claude-code-style top-level cost
                "token_totals": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cost_usd": 0.99,  # nested value should be ignored when top-level set
                },
            },
        ), patch.object(
            ExploitWorkflow, "evaluate", return_value={"scores": {}}
        ), patch.object(
            ExploitWorkflow, "cleanup"
        ):
            assert run(base_config, "test_app", tmp_path) == 0

        with open(
            logger_manager.get_logs_dir() / "run_summary.json", encoding="utf-8"
        ) as f:
            summary = json.load(f)
        assert summary["metrics"]["cost_usd"] == 0.42
        validate(instance=summary, schema=_load_run_summary_schema())

    def test_run_summary_schema_declares_cost_usd(self):
        """`metrics.cost_usd` is part of the run_summary contract.
        """
        schema = _load_run_summary_schema()
        metrics = schema["properties"]["metrics"]
        assert "cost_usd" in metrics["required"]
        assert metrics["properties"]["cost_usd"] == {"type": ["number", "null"]}

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


class TestAttackerModelConfig:
    """Tests for attacker_model configuration."""

    def test_remote_attacker_valid_with_redteam(self, base_config):
        config = RunnerConfig(
            **{
                **base_config.model_dump(),
                "workflow": "redteam",
                "task": "report-0",
                "synthetic_vuln_id": None,
                "attacker_model": "remote_attacker",
            }
        )
        assert config.attacker_model == "remote_attacker"

    def test_remote_attacker_rejected_with_exploit(self, base_config):
        with pytest.raises(ValueError, match="requires workflow='redteam'"):
            RunnerConfig(
                **{
                    **base_config.model_dump(),
                    "workflow": "exploit",
                    "attacker_model": "remote_attacker",
                }
            )

    def test_malicious_app_rejected_with_exploit(self, base_config):
        with pytest.raises(ValueError, match="requires workflow='redteam'"):
            RunnerConfig(
                **{
                    **base_config.model_dump(),
                    "workflow": "exploit",
                    "attacker_model": "malicious_app",
                }
            )

    def test_attacker_model_default_is_none(self, base_config):
        """attacker_model has no silent default; task metadata is authoritative."""
        config = RunnerConfig(
            **{
                **base_config.model_dump(),
                "workflow": "redteam",
                "task": "report-0",
                "synthetic_vuln_id": None,
            }
        )
        assert config.attacker_model is None

    def test_invalid_attacker_model_rejected(self, base_config):
        with pytest.raises(ValueError):
            RunnerConfig(
                **{
                    **base_config.model_dump(),
                    "workflow": "redteam",
                    "task": "report-0",
                    "synthetic_vuln_id": None,
                    "attacker_model": "bogus",
                }
            )


class TestTaskMetadataOverride:
    """task/metadata.json overrides config.attacker_model before workflow creation."""

    def test_overrides_attacker_model_from_task_metadata(self, base_config, tmp_path):
        """run() reconciles attacker_model from task/metadata.json for the workflow."""
        task_dir = tmp_path / "zerodays" / "reports" / "testapp" / "report-4" / "task"
        task_dir.mkdir(parents=True)
        (task_dir / "metadata.json").write_text(
            json.dumps({"attacker_model": "remote_attacker"})
        )

        config = RunnerConfig(
            **{
                **base_config.model_dump(),
                "workflow": "redteam",
                "task": "report-4",
                "synthetic_vuln_id": None,
            }
        )
        assert config.attacker_model is None

        captured = {}

        def spy(cfg, app_name, project_root):
            captured["attacker_model"] = cfg.attacker_model
            raise RuntimeError("stop before workflow setup")

        with patch("runner.ensure_app_submodule"), patch(
            "runner.create_workflow", side_effect=spy
        ):
            run(config, "testapp", tmp_path)

        assert captured["attacker_model"] == "remote_attacker"
        # Caller's config is unchanged — reconciliation is purely local to run().
        assert config.attacker_model is None

    def test_missing_attacker_model_in_task_metadata_fails(self, base_config, tmp_path):
        """task/metadata.json with missing attacker_model returns exit code 1."""
        task_dir = tmp_path / "zerodays" / "reports" / "testapp" / "report-0" / "task"
        task_dir.mkdir(parents=True)
        (task_dir / "metadata.json").write_text(json.dumps({"title": "no model"}))

        config = RunnerConfig(
            **{
                **base_config.model_dump(),
                "workflow": "redteam",
                "task": "report-0",
                "synthetic_vuln_id": None,
            }
        )
        exit_code = run(config, "testapp", tmp_path)
        assert exit_code == 1


class TestReplayMetadataOverride:
    """Replay metadata must normalize selectors for TaskBundle XOR."""

    def test_zeroday_replay_clears_stale_synthetic_vuln_id(self, base_config, tmp_path):
        config = RunnerConfig(
            **{**base_config.model_dump(), "replay_run": "logs/exp-1"}
        )
        replay = ExploitSource(
            kind="replay",
            source_dir=tmp_path / "logs" / "exp-1" / "agent_exploit",
            app_name="testapp",
            workflow="redteam",
            task="report-9",
            synthetic_vuln_id=None,
            attacker_model="remote_attacker",
        )
        captured = {}

        def spy(cfg, app_name, project_root):
            captured["workflow"] = cfg.workflow
            captured["task"] = cfg.task
            captured["synthetic_vuln_id"] = cfg.synthetic_vuln_id
            captured["attacker_model"] = cfg.attacker_model
            raise RuntimeError("stop before workflow setup")

        with patch("runner.ensure_app_submodule"), patch(
            "runner.create_workflow", side_effect=spy
        ):
            run(config, "testapp", tmp_path, exploit_source=replay)

        assert captured == {
            "workflow": "redteam",
            "task": "report-9",
            "synthetic_vuln_id": None,
            "attacker_model": "remote_attacker",
        }

    def test_synthetic_redteam_replay_clears_stale_task(self, base_config, tmp_path):
        config = RunnerConfig(
            **{
                **base_config.model_dump(),
                "task": "stale-report",
                "replay_run": "logs/exp-2",
            }
        )
        replay = ExploitSource(
            kind="replay",
            source_dir=tmp_path / "logs" / "exp-2" / "agent_exploit",
            app_name="testapp",
            workflow="redteam",
            task=None,
            synthetic_vuln_id="vuln_7",
            attacker_model="malicious_app",
        )
        captured = {}

        def spy(cfg, app_name, project_root):
            captured["workflow"] = cfg.workflow
            captured["task"] = cfg.task
            captured["synthetic_vuln_id"] = cfg.synthetic_vuln_id
            captured["attacker_model"] = cfg.attacker_model
            raise RuntimeError("stop before workflow setup")

        with patch("runner.ensure_app_submodule"), patch(
            "runner.create_workflow", side_effect=spy
        ):
            run(config, "testapp", tmp_path, exploit_source=replay)

        assert captured == {
            "workflow": "redteam",
            "task": None,
            "synthetic_vuln_id": "vuln_7",
            "attacker_model": "malicious_app",
        }


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
