"""Tests for runner.py - Workflow-based runner."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from jsonschema import validate

from models.config import RunnerConfig
from models.resolved_config import resolve_runner_config
from runner import create_workflow, main, run
from tests.conftest import (
    custom_agent,
    external_agent,
    make_config,
    probe_only_workflow,
    redteam_zeroday_workflow,
)
from utils.logger import logger_manager
from workflows import ExploitWorkflow


def _load_run_summary_schema() -> dict:
    schema_path = Path(__file__).parent.parent / "schemas" / "run_summary.schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def base_config():
    """Exploit-workflow nested RunnerConfig for shared TestRun cases."""
    return make_config()


class TestCreateWorkflow:
    """Tests for workflow selection logic."""

    def test_creates_exploit_workflow_by_default(self, tmp_path):
        resolved = resolve_runner_config(
            make_config(), app_name="test_app", project_root=tmp_path
        )
        assert isinstance(
            create_workflow(resolved, "test_app", tmp_path), ExploitWorkflow
        )

    def test_creates_redteam_workflow_when_configured(self, tmp_path):
        from workflows import RedTeamWorkflow

        task_dir = tmp_path / "zerodays" / "reports" / "test_app" / "report-0" / "task"
        task_dir.mkdir(parents=True)
        (task_dir / "metadata.json").write_text(
            json.dumps({"attacker_model": "malicious_app"})
        )

        rt_config = make_config(workflow=redteam_zeroday_workflow(task="report-0"))
        resolved = resolve_runner_config(
            rt_config, app_name="test_app", project_root=tmp_path
        )
        assert isinstance(
            create_workflow(resolved, "test_app", tmp_path), RedTeamWorkflow
        )

    def test_gold_execution_allowed_with_redteam_zeroday(self):
        cfg = make_config(
            workflow=redteam_zeroday_workflow(task="report-0"),
            execution_mode="gold",
        )
        assert cfg.execution.mode == "gold"

    def test_redteam_synthetic_requires_vuln_id(self):
        """Discriminated workflow union requires the variant's selectors."""
        with pytest.raises(ValueError):
            RunnerConfig.model_validate(
                {
                    "workflow": {"kind": "redteam_synthetic"},
                    "agent": custom_agent(),
                    "runtime": {"build_type": "source"},
                }
            )

    @pytest.mark.parametrize("legacy_mode", ["codex", "claude-code"])
    def test_legacy_agent_mode_rejected(self, legacy_mode):
        with pytest.raises(ValueError):
            make_config(agent={"mode": legacy_mode, "image": "x", "model": "y"})


class TestImageModelCompat:
    """agent.image (CLI family) ↔ agent.model (provider family) compatibility."""

    @pytest.mark.parametrize(
        "image, model",
        [
            ("cybench/mobilecybench:claudecode_2.1.140-r2", "claude-opus-4-7"),
            ("cybench/mobilecybench:codex_0.130.0-r2", "gpt-5.5"),
        ],
    )
    def test_matching_cli_and_provider_ok(self, image, model):
        cfg = make_config(agent=external_agent(image=image, model=model))
        assert cfg.agent.image == image and cfg.agent.model == model

    @pytest.mark.parametrize(
        "image, model, cli",
        [
            ("cybench/mobilecybench:claudecode_2.1.140-r2", "gpt-5.5", "claudecode"),
            ("cybench/mobilecybench:codex_0.130.0-r2", "claude-opus-4-7", "codex"),
            ("cybench/mobilecybench:codex_0.130.0-r2", "gemini-3.1-pro", "codex"),
        ],
    )
    def test_mismatch_rejected(self, image, model, cli):
        with pytest.raises(ValueError, match=cli):
            make_config(agent=external_agent(image=image, model=model))

    def test_unknown_image_tag_is_permissive(self):
        """Lab/BYO images bypass the CLI-prefix compat check."""
        cfg = make_config(
            agent=external_agent(image="lab/mycli:0.1", model="gemini-3.1-pro")
        )
        assert cfg.agent.image == "lab/mycli:0.1"

    def test_custom_mode_skips_check(self):
        """Image-compat applies only to external mode."""
        cfg = make_config(
            agent=custom_agent(
                image="cybench/mobilecybench:claudecode_2.1.140-r2", model="gpt-5.5"
            )
        )
        assert cfg.agent.mode == "custom"

    @pytest.mark.parametrize(
        "model",
        [
            "opus-4-7",
            "claude-opus-4-typoz",
            "gpt-5.5-typo",
        ],
    )
    def test_external_unknown_model_rejected(self, model):
        with pytest.raises(ValueError, match="Unknown model"):
            make_config(
                agent=external_agent(
                    image="cybench/mobilecybench:claudecode_2.1.140-r2", model=model
                )
            )

    def test_external_unknown_model_allowed_with_opt_in(self):
        cfg = make_config(
            agent=external_agent(
                image="lab/mycli:0.1",
                model="future-model-not-yet-registered",
                allow_unregistered_models=True,
            )
        )
        assert cfg.agent.model == "future-model-not-yet-registered"


class TestProbeOnlyValidators:
    """Probe-only scores via probes only. ``dry_run`` and ``gold`` bypass
    scoring and are rejected at config-load."""

    def test_probe_only_with_dry_run_rejected(self):
        with pytest.raises(
            ValueError, match=r"dry_run.*invalid for redteam_probe_only"
        ):
            make_config(workflow=probe_only_workflow(), execution_mode="dry_run")

    def test_probe_only_with_gold_rejected(self):
        with pytest.raises(ValueError, match=r"gold.*invalid for redteam_probe_only"):
            make_config(workflow=probe_only_workflow(), execution_mode="gold")


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
                self.app_dir.mkdir(parents=True, exist_ok=True)

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

        from tests.conftest import redteam_synthetic_workflow

        config = make_config(
            workflow=redteam_synthetic_workflow(synthetic_vuln_id="vuln_0")
        )

        # resolve_runner_config reads attacker_model from the bundle's
        # metadata.json — write a real one instead of patching the helper.
        vuln_dir = (
            tmp_path / "apps" / "test_app" / "synthetic_vulnerabilities" / "vuln_0"
        )
        vuln_dir.mkdir(parents=True)
        (vuln_dir / "metadata.json").write_text(
            json.dumps({"attacker_model": "malicious_app"})
        )

        with patch("runner.ensure_app_submodule"), patch(
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
        dry_run_config = make_config(execution_mode="dry_run")

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
        dry_run_config = make_config(execution_mode="dry_run")

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
        assert (
            summary["config"]["effective"]["runtime"]["build_type"]
            == base_config.runtime.build_type
        )
        # Schema-required effective view is fully populated, never None.
        assert summary["config"]["effective"]["agent"]["mode"] == "custom"
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


class TestProbeOnlyAttackerModel:
    def test_probe_only_invalid_attacker_model_rejected(self):
        """probe-only attacker_model is a Literal; pydantic rejects unknown values."""
        with pytest.raises(ValueError):
            make_config(workflow=probe_only_workflow(attacker_model="bogus"))


class TestTaskMetadataOverride:
    """Bundle metadata.json is the authoritative source of attacker_model for
    redteam_zeroday / redteam_synthetic. ``resolve_runner_config`` reads it
    once during resolution; downstream code sees
    ``resolved.workflow.attacker_model`` (after narrowing to a redteam variant)."""

    def test_resolves_attacker_model_from_task_metadata(self, tmp_path):
        task_dir = tmp_path / "zerodays" / "reports" / "testapp" / "report-4" / "task"
        task_dir.mkdir(parents=True)
        (task_dir / "metadata.json").write_text(
            json.dumps({"attacker_model": "remote_attacker"})
        )

        config = make_config(workflow=redteam_zeroday_workflow(task="report-4"))
        resolved = resolve_runner_config(
            config, app_name="testapp", project_root=tmp_path
        )
        assert resolved.workflow.attacker_model == "remote_attacker"

    def test_missing_attacker_model_in_task_metadata_fails(self, tmp_path):
        """task/metadata.json with missing attacker_model returns exit code 1."""
        task_dir = tmp_path / "zerodays" / "reports" / "testapp" / "report-0" / "task"
        task_dir.mkdir(parents=True)
        (task_dir / "metadata.json").write_text(json.dumps({"title": "no model"}))

        config = make_config(workflow=redteam_zeroday_workflow(task="report-0"))
        assert run(config, "testapp", tmp_path) == 1


class TestZerodaySubmoduleInit:
    """``ensure_zerodays_submodule`` must run before ``validate_arguments`` for
    zeroday tasks; otherwise validation surfaces a misleading "Task file not
    found" error instead of the submodule-init hint."""

    def test_zerodays_init_runs_for_redteam_task_before_validate(self, tmp_path):
        config = make_config(workflow=redteam_zeroday_workflow(task="report-4"))
        task_dir = tmp_path / "zerodays" / "reports" / "testapp" / "report-4" / "task"

        order = []

        def init_zerodays(*_args, **_kwargs):
            order.append("zerodays_init")
            task_dir.mkdir(parents=True)
            (task_dir / "metadata.json").write_text(
                json.dumps({"attacker_model": "remote_attacker"})
            )

        def fail_validate(self):
            order.append("validate")
            raise RuntimeError("stop")

        with patch(
            "runner.ensure_zerodays_submodule",
            side_effect=init_zerodays,
        ), patch("runner.ensure_app_submodule"), patch(
            "workflows.RedTeamWorkflow.validate_arguments", new=fail_validate
        ):
            run(config, "testapp", tmp_path)

        assert order == ["zerodays_init", "validate"]


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
