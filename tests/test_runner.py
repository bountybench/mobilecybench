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


@pytest.fixture
def base_config():
    """Base configuration for testing."""
    return RunnerConfig(
        build_type="source",
        max_iterations=10,
        max_model_response_tokens=1000,
        model="gpt-4",
        screenshot_mode=False,
        dry_run=False,
        agent_image="test-image:latest",
        emulator_display="headed",
        emulator_backend="native",
        network_mode="restricted",
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

        # Bundle now owns attacker_model — seed task metadata.json so workflow
        # init can read it.
        task_dir = tmp_path / "zerodays" / "reports" / "test_app" / "report-0" / "task"
        task_dir.mkdir(parents=True)
        (task_dir / "metadata.json").write_text(
            json.dumps({"attacker_model": "malicious_app"})
        )

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

    @pytest.mark.parametrize(
        "legacy_mode, expected_image_hint",
        [
            ("codex", "codex_0.130.0-r2"),
            ("claude-code", "claudecode_2.1.140-r2"),
        ],
    )
    def test_legacy_agent_mode_raises_migration_hint(
        self, base_config, legacy_mode, expected_image_hint
    ):
        """Pre-BYO ``agent_mode`` values are rejected with a migration string."""
        with pytest.raises(ValueError, match=expected_image_hint):
            RunnerConfig(**{**base_config.model_dump(), "agent_mode": legacy_mode})


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

    def test_redteam_missing_evaluation_score_fails(self, base_config, tmp_path):
        """Redteam evaluation without a top-level score is a runner failure."""

        class FakeRedTeamWorkflow:
            metadata = {}
            agent_env = None
            emulator = None

            def __init__(self):
                self.app_dir = tmp_path / "apps" / "test_app"
                self.app_dir.mkdir(parents=True)

            def validate_arguments(self):
                pass

            def setup_runtime_environment(self):
                pass

            def setup_agent(self):
                pass

            def run_agent(self):
                return {"status": "completed"}

            def save_artifacts(self, logs_dir):
                pass

            def evaluate(self):
                return {}

            def cleanup(self):
                pass

        config = RunnerConfig(
            **{
                **base_config.model_dump(),
                "workflow": "redteam",
                "task": None,
                "synthetic_vuln_id": "vuln_0",
                "attacker_model": "malicious_app",
            }
        )

        with patch(
            "runner._load_bundle_attacker_model", return_value="malicious_app"
        ), patch("runner.ensure_app_submodule"), patch(
            "runner.create_workflow", return_value=FakeRedTeamWorkflow()
        ):
            result = run(config, "test_app", tmp_path)

        assert result == 1
        with open(
            logger_manager.get_logs_dir() / "run_summary.json", encoding="utf-8"
        ) as f:
            summary = json.load(f)

        assert summary["outcome"] == "failure"
        assert summary["exit_reason"] == "missing_evaluation"
        assert summary["results"]["score"] is None
        assert (
            "redteam evaluation did not produce a score"
            in summary["results"]["inconsistencies"]
        )
        validate(instance=summary, schema=_load_run_summary_schema())

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

    def test_save_artifacts_called_when_agent_crashes(self, base_config, tmp_path):
        """save_artifacts runs even if run_agent raises an exception, to be performed before container cleanup."""
        call_order = []

        with patch("runner.ensure_app_submodule"), patch.object(
            ExploitWorkflow, "validate_arguments"
        ), patch.object(ExploitWorkflow, "setup_runtime_environment"), patch.object(
            ExploitWorkflow, "setup_agent"
        ), patch.object(
            ExploitWorkflow, "run_agent", side_effect=Exception("Agent crashed")
        ), patch.object(
            ExploitWorkflow,
            "save_artifacts",
            side_effect=lambda *a, **kw: call_order.append("save_artifacts"),
        ) as mock_save, patch.object(
            ExploitWorkflow,
            "cleanup",
            side_effect=lambda *a, **kw: call_order.append("cleanup"),
        ):

            run(base_config, "test_app", tmp_path)

            mock_save.assert_called_once()
            assert call_order.index("save_artifacts") < call_order.index("cleanup")

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

    def test_dry_run_saves_artifacts_before_cleanup(self, base_config, tmp_path):
        """Dry-run sidecar logs are captured before final cleanup removes them."""
        call_order = []
        dry_run_config = RunnerConfig(**{**base_config.model_dump(), "dry_run": True})

        class FakeWorkflow:
            metadata = {}
            emulator = None
            agent_env = object()

            def __init__(self):
                self.app_dir = tmp_path / "apps" / "test_app"

            def validate_arguments(self):
                pass

            def setup_runtime_environment(self):
                pass

            def save_artifacts(self, logs_dir):
                call_order.append("save_artifacts")

            def cleanup(self):
                call_order.append("cleanup")

        with patch("runner.ensure_app_submodule"), patch(
            "runner.create_workflow", return_value=FakeWorkflow()
        ), patch("runner.run_interactive_shell", return_value={"status": "completed"}):
            assert run(dry_run_config, "test_app", tmp_path) == 0

        assert call_order == ["save_artifacts", "cleanup"]

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
                # cost_usd is top-level; token_totals carries token counts only.
                "cost_usd": 0.1,
                "token_totals": {
                    "input_tokens": 10,
                    "output_tokens": 5,
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
        assert summary_path.exists()

        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)

        assert summary["run_id"]
        assert summary["outcome"] == "success"
        assert summary["context"]["app_name"] == "test_app"
        assert summary["config"]["build_type"] == base_config.build_type
        assert summary["metrics"]["turn_count"] == 2
        assert summary["metrics"]["tool_call_count"] == 1
        assert summary["metrics"]["cost_usd"] == 0.1
        assert "cost_usd" not in summary["metrics"]["token_totals"]
        assert summary["results"]["scores"] == {"probe_a": 1}
        assert "conversation_jsonl" in summary["artifacts"]
        validate(instance=summary, schema=_load_run_summary_schema())

    def test_run_summary_includes_captured_squid_logs(self, base_config, tmp_path):
        """Run summary points at Squid logs captured before firewall cleanup."""

        def save_squid_logs(*args):
            logs_dir = Path(args[-1])
            (logs_dir / "squid_access.log").write_text(
                "TCP_DENIED example.com\n", encoding="utf-8"
            )
            (logs_dir / "squid_cache.log").write_text(
                "Squid cache entry\n", encoding="utf-8"
            )

        with patch("runner.ensure_app_submodule"), patch.object(
            ExploitWorkflow, "validate_arguments"
        ), patch.object(ExploitWorkflow, "setup_runtime_environment"), patch.object(
            ExploitWorkflow, "setup_agent"
        ), patch.object(
            ExploitWorkflow,
            "run_agent",
            return_value={"status": "completed"},
        ), patch.object(
            ExploitWorkflow, "save_artifacts", side_effect=save_squid_logs
        ), patch.object(
            ExploitWorkflow, "evaluate", return_value={"scores": {"probe_a": 1}}
        ), patch.object(
            ExploitWorkflow, "cleanup"
        ):
            assert run(base_config, "test_app", tmp_path) == 0

        summary_path = logger_manager.get_logs_dir() / "run_summary.json"
        with open(summary_path, "r", encoding="utf-8") as f:
            summary = json.load(f)

        artifacts = summary["artifacts"]
        assert artifacts["squid_access_log"] == "squid_access.log"
        assert artifacts["squid_cache_log"] == "squid_cache.log"
        assert (summary_path.parent / artifacts["squid_access_log"]).read_text(
            encoding="utf-8"
        ) == "TCP_DENIED example.com\n"
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
        """`metrics.cost_usd` is part of the run_summary contract."""
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

    def test_canonical_conversation_jsonl_is_recorded(self, base_config, tmp_path):
        """If agent_run/conversation.jsonl exists on disk, run_summary points to it.
        Both custom and BYO write to this canonical path; consumers should find it
        without the agent stamping a redundant path field."""

        def write_canonical_conversation():
            agent_run = logger_manager.get_logs_dir() / "agent_run"
            agent_run.mkdir(parents=True, exist_ok=True)
            (agent_run / "conversation.jsonl").write_text(
                '{"run_id":"r","turn_number":1,"timestamp":"2026-01-01T00:00:00+00:00",'
                '"role":"assistant","assistant_text":"done","tool_calls":[],'
                '"observations":[],"status":"ok"}\n',
                encoding="utf-8",
            )

        def setup_agent_writes_conversation(*_a, **_kw):
            write_canonical_conversation()

        with patch("runner.ensure_app_submodule"), patch.object(
            ExploitWorkflow, "validate_arguments"
        ), patch.object(ExploitWorkflow, "setup_runtime_environment"), patch.object(
            ExploitWorkflow, "setup_agent", side_effect=setup_agent_writes_conversation
        ), patch.object(
            ExploitWorkflow,
            "run_agent",
            return_value={
                "status": "completed",
                "turns_taken": 1,
                "token_totals": {"input_tokens": 1, "output_tokens": 1},
            },
        ), patch.object(
            ExploitWorkflow, "evaluate", return_value={"scores": {"probe_a": 1}}
        ), patch.object(
            ExploitWorkflow, "cleanup"
        ):
            assert run(base_config, "test_app", tmp_path) == 0

        summary_path = logger_manager.get_logs_dir() / "run_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        conversation_rel = summary["artifacts"]["conversation_jsonl"]
        assert conversation_rel is not None
        assert (summary_path.parent / conversation_rel).exists()


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


class TestZerodaySubmoduleInit:
    """zerodays/ submodule must be lazy-initialized BEFORE validate_arguments
    for redteam tasks, otherwise validation surfaces a misleading 'Task file
    not found' error instead of an init hint."""

    def test_zerodays_init_runs_for_redteam_task_before_validate(
        self, base_config, tmp_path
    ):
        config = RunnerConfig(
            **{
                **base_config.model_dump(),
                "workflow": "redteam",
                "task": "report-4",
                "synthetic_vuln_id": None,
                "attacker_model": "remote_attacker",
            }
        )
        # Make task metadata read succeed so flow reaches the init step.
        task_dir = tmp_path / "zerodays" / "reports" / "testapp" / "report-4" / "task"
        task_dir.mkdir(parents=True)
        (task_dir / "metadata.json").write_text(
            json.dumps({"attacker_model": "remote_attacker"})
        )

        order = []

        def fail_validate(self):
            order.append("validate")
            raise RuntimeError("stop")

        with patch(
            "runner.ensure_zerodays_submodule",
            side_effect=lambda *a, **k: order.append("zerodays_init"),
        ), patch("runner.ensure_app_submodule"), patch(
            "workflows.RedTeamWorkflow.validate_arguments", new=fail_validate
        ):
            run(config, "testapp", tmp_path)

        assert order == ["zerodays_init", "validate"]


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

    def test_redteam_replay_clears_stale_probe_only_flag(self, base_config, tmp_path):
        """Operator's current config may carry probe_only=True (their last
        run) while replaying a two-phase saved run. The replay-validation
        bypass in models/config.py would otherwise let probe_only=True
        survive into resolve_bundle, which routes on probe_only first and
        would silently return ProbeOnlyBundle — converting a two-phase
        replay into probe-only with no warning. Force probe_only=False
        for any accepted replay source (resolve_replay_source already
        rejects probe-only snapshots upstream)."""
        # probe_only is redteam-only; the realistic scenario is the operator's
        # current (saved) config is a redteam probe-only run, then they
        # invoke replay against an unrelated two-phase artifact.
        config = RunnerConfig(
            **{
                **base_config.model_dump(),
                "workflow": "redteam",
                "task": None,
                "synthetic_vuln_id": None,
                "attacker_model": "malicious_app",
                "probe_only": True,  # stale from a prior probe-only run
                "replay_run": "logs/exp-3",
            }
        )
        replay = ExploitSource(
            kind="replay",
            source_dir=tmp_path / "logs" / "exp-3" / "agent_exploit",
            app_name="testapp",
            workflow="redteam",
            task="report-5",
            synthetic_vuln_id=None,
            attacker_model="remote_attacker",
        )
        captured = {}

        def spy(cfg, app_name, project_root):
            captured["probe_only"] = cfg.probe_only
            captured["task"] = cfg.task
            captured["attacker_model"] = cfg.attacker_model
            raise RuntimeError("stop before workflow setup")

        with patch("runner.ensure_app_submodule"), patch(
            "runner.create_workflow", side_effect=spy
        ):
            run(config, "testapp", tmp_path, exploit_source=replay)

        assert captured == {
            "probe_only": False,
            "task": "report-5",
            "attacker_model": "remote_attacker",
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
