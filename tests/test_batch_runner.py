import json
import logging
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

import batch_runner
from models.config import BatchRunnerConfig, BatchSpec, RunnerConfig
from utils.logger import agent_logger, logger, logger_manager

REPO_ROOT = Path(__file__).resolve().parents[1]


def _base_payload() -> dict:
    return {
        "workflow": "redteam",
        "probe_only": True,
        "task": None,
        "synthetic_vuln_id": None,
        "no_codebase": False,
        "apk_obfuscation": "off",
        "agent_mode": "external",
        "agent_image": "test-image:latest",
        "model": "test-model",
        "max_iterations": 10,
        "max_model_response_tokens": 1000,
        "build_type": "download-apk",
        "emulator_display": "headless",
        "network_mode": "permissive",
        "dry_run": False,
        "gold_run": False,
    }


def _write_catalog(tmp_path: Path, apps: list[str]) -> Path:
    catalog = tmp_path / "apps" / "app_catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(
        json.dumps(
            {"sets": {"in_scope": apps}},
        ),
        encoding="utf-8",
    )
    return catalog


def test_default_batch_matrix_runs_in_scope_apps_times_two_attacker_models(tmp_path):
    _write_catalog(tmp_path, ["app_a", "app_b"])
    batch = BatchSpec()

    jobs = batch_runner.expand_batch_jobs(_base_payload(), batch, tmp_path)

    assert [(job.app_name, job.config.attacker_model) for job in jobs] == [
        ("app_a", "malicious_app"),
        ("app_a", "remote_attacker"),
        ("app_b", "malicious_app"),
        ("app_b", "remote_attacker"),
    ]


def test_batch_matrix_cycles_arbitrary_runner_config_fields(tmp_path):
    _write_catalog(tmp_path, ["app_a"])
    batch = BatchSpec(
        matrix={
            "attacker_model": ["remote_attacker"],
            "no_codebase": [False, True],
        }
    )

    jobs = batch_runner.expand_batch_jobs(_base_payload(), batch, tmp_path)

    assert [(job.config.attacker_model, job.config.no_codebase) for job in jobs] == [
        ("remote_attacker", False),
        ("remote_attacker", True),
    ]


def test_batch_matrix_can_cycle_apps_as_an_axis(tmp_path):
    batch = BatchSpec(
        matrix={
            "app": ["conversations", "jitsi-meet"],
            "model": ["gpt-5.5", "claude-opus-4-8"],
            "attacker_model": ["remote_attacker"],
        }
    )

    jobs = batch_runner.expand_batch_jobs(_base_payload(), batch, tmp_path)

    assert {(job.app_name, job.config.model) for job in jobs} == {
        ("conversations", "gpt-5.5"),
        ("conversations", "claude-opus-4-8"),
        ("jitsi-meet", "gpt-5.5"),
        ("jitsi-meet", "claude-opus-4-8"),
    }
    assert all(job.config.attacker_model == "remote_attacker" for job in jobs)
    assert all("app" in job.overrides for job in jobs)


def test_batch_matrix_keeps_default_attacker_models_when_not_overridden(tmp_path):
    _write_catalog(tmp_path, ["app_a"])
    batch = BatchSpec(matrix={"no_codebase": [False, True]})

    jobs = batch_runner.expand_batch_jobs(_base_payload(), batch, tmp_path)

    assert [(job.config.attacker_model, job.config.no_codebase) for job in jobs] == [
        ("malicious_app", False),
        ("malicious_app", True),
        ("remote_attacker", False),
        ("remote_attacker", True),
    ]


def test_batch_apps_can_be_explicit_subset_without_catalog(tmp_path):
    batch = BatchSpec(
        apps=["wallabag"],
        matrix={"attacker_model": ["malicious_app"]},
    )

    jobs = batch_runner.expand_batch_jobs(_base_payload(), batch, tmp_path)

    assert len(jobs) == 1
    assert jobs[0].app_name == "wallabag"
    assert jobs[0].config.attacker_model == "malicious_app"


def test_batch_exclude_skips_matching_cells(tmp_path):
    _write_catalog(tmp_path, ["app_a", "app_b"])
    batch = BatchSpec(exclude=[{"app": "app_b", "attacker_model": "remote_attacker"}])

    jobs = batch_runner.expand_batch_jobs(_base_payload(), batch, tmp_path)

    assert [(job.app_name, job.config.attacker_model) for job in jobs] == [
        ("app_a", "malicious_app"),
        ("app_a", "remote_attacker"),
        ("app_b", "malicious_app"),
    ]


def test_batch_exclude_matches_runner_config_defaults(tmp_path):
    _write_catalog(tmp_path, ["app_a"])
    batch = BatchSpec(
        exclude=[{"attacker_model": "malicious_app", "probe_baseline_diff": False}]
    )

    jobs = batch_runner.expand_batch_jobs(_base_payload(), batch, tmp_path)

    assert [(job.app_name, job.config.attacker_model) for job in jobs] == [
        ("app_a", "remote_attacker"),
    ]


def test_batch_exclude_matches_coerced_runner_config_values(tmp_path):
    _write_catalog(tmp_path, ["app_a"])
    batch = BatchSpec(
        matrix={
            "attacker_model": ["malicious_app", "remote_attacker"],
            "no_codebase": ["false"],
        },
        exclude=[{"attacker_model": "remote_attacker", "no_codebase": False}],
    )

    jobs = batch_runner.expand_batch_jobs(_base_payload(), batch, tmp_path)

    assert [(job.config.attacker_model, job.config.no_codebase) for job in jobs] == [
        ("malicious_app", False),
    ]


def test_batch_exclude_coerces_exclude_values_to_runner_config_types(tmp_path):
    _write_catalog(tmp_path, ["app_a"])
    batch = BatchSpec(
        matrix={
            "attacker_model": ["malicious_app", "remote_attacker"],
            "gold_run": ["false"],
        },
        exclude=[{"gold_run": "false"}],
    )

    with pytest.raises(ValueError, match="zero jobs"):
        batch_runner.expand_batch_jobs(_base_payload(), batch, tmp_path)


def test_batch_exclude_can_skip_invalid_cell_using_defaulted_values(tmp_path):
    _write_catalog(tmp_path, ["app_a"])
    batch = BatchSpec(
        matrix={
            "attacker_model": ["malicious_app"],
            "apk_obfuscation": ["on"],
        },
        exclude=[{"no_codebase": False, "apk_obfuscation": "on"}],
    )

    with pytest.raises(ValueError, match="zero jobs"):
        batch_runner.expand_batch_jobs(_base_payload(), batch, tmp_path)


def test_expand_batch_jobs_ignores_tooling_only_schema_key(tmp_path):
    _write_catalog(tmp_path, ["app_a"])
    batch = BatchSpec(matrix={"attacker_model": ["remote_attacker"]})

    jobs = batch_runner.expand_batch_jobs(
        {**_base_payload(), "$schema": "schemas/batch_runner_config.schema.json"},
        batch,
        tmp_path,
    )

    assert len(jobs) == 1
    assert jobs[0].config.attacker_model == "remote_attacker"


def test_batch_matrix_rejects_unknown_runner_config_field():
    with pytest.raises(ValueError, match="not a RunnerConfig field"):
        BatchSpec(matrix={"bogus": [1]})


def test_runner_config_from_file_ignores_batch_block_for_single_app(tmp_path):
    config_path = tmp_path / "config.json"
    payload = {
        **_base_payload(),
        "attacker_model": "remote_attacker",
        "batch": {"apps": "in_scope"},
    }
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    config = RunnerConfig.from_file(config_path)

    assert config.attacker_model == "remote_attacker"


def test_run_batch_executes_jobs_sequentially_and_writes_summary(tmp_path, monkeypatch):
    _write_catalog(tmp_path, ["app_a"])
    batch = BatchSpec(matrix={"attacker_model": ["malicious_app", "remote_attacker"]})
    calls = []
    observed_runs = []
    observed_agent_handlers = []

    logs_root = tmp_path / "logs"
    monkeypatch.setenv("MOBILECYBENCH_LOGS_DIR", str(logs_root))
    monkeypatch.delenv("MOBILECYBENCH_SESSION_ID", raising=False)

    def fake_run(config, app_name, project_root, config_path=None):
        run_id = logger_manager.get_run_id()
        logs_dir = logger_manager.get_logs_dir()
        agent_log = Path(logger_manager.get_agent_log_file_name())
        assert logs_dir is not None
        assert agent_log == logs_dir / "agent_run" / "agent.log"
        calls.append((app_name, config.attacker_model))
        observed_runs.append((run_id, logs_dir, agent_log, config.attacker_model))
        agent_file_handlers = [
            h for h in agent_logger.handlers if isinstance(h, logging.FileHandler)
        ]
        assert len(agent_file_handlers) == 1
        observed_agent_handlers.append(agent_file_handlers[0])

        # Mirrors the normal single-run path, which updates logs/latest inside
        # runner.run(). The batch layer should not special-case that singleton.
        logger_manager.update_latest_symlink()

        logger.info("main-log-marker-%s", config.attacker_model)
        agent_logger.info("agent-log-marker-%s", config.attacker_model)
        (logs_dir / "run_summary.json").write_text(
            json.dumps(
                {
                    "outcome": "success",
                    "exit_reason": "completed",
                    "results": {"score": 1},
                }
            ),
            encoding="utf-8",
        )
        return 0

    assert (
        batch_runner.run_batch(
            _base_payload(),
            batch,
            tmp_path,
            run_func=fake_run,
            config_path=None,
        )
        == 0
    )

    assert calls == [("app_a", "malicious_app"), ("app_a", "remote_attacker")]
    assert len({run_id for run_id, *_ in observed_runs}) == 2
    assert len({logs_dir for _, logs_dir, *_ in observed_runs}) == 2
    assert observed_agent_handlers[0] is not observed_agent_handlers[1]
    assert observed_agent_handlers[0].stream is None
    assert observed_agent_handlers[1].stream is not None
    summaries = list((logs_root / "batches").glob("batch_*/batch_summary.json"))
    assert len(summaries) == 1
    summary = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert summary["status"] == "completed"
    assert summary["total_jobs"] == 2
    assert summary["completed_jobs"] == 2
    assert [job["overrides"]["attacker_model"] for job in summary["jobs"]] == [
        "malicious_app",
        "remote_attacker",
    ]
    assert all(Path(job["logs_dir"]).is_dir() for job in summary["jobs"])
    assert all(Path(job["run_summary"]).is_file() for job in summary["jobs"])

    first_run = observed_runs[0]
    second_run = observed_runs[1]
    assert (logs_root / "latest").resolve() == second_run[1].resolve()

    first_experiment_log = first_run[1] / "experiment.log"
    second_experiment_log = second_run[1] / "experiment.log"
    first_agent_log = first_run[2]
    second_agent_log = second_run[2]
    for path in (
        first_experiment_log,
        second_experiment_log,
        first_agent_log,
        second_agent_log,
    ):
        assert path.is_file()

    assert "main-log-marker-malicious_app" in first_experiment_log.read_text(
        encoding="utf-8"
    )
    assert "main-log-marker-remote_attacker" not in first_experiment_log.read_text(
        encoding="utf-8"
    )
    assert "agent-log-marker-remote_attacker" not in first_experiment_log.read_text(
        encoding="utf-8"
    )
    assert "main-log-marker-remote_attacker" in second_experiment_log.read_text(
        encoding="utf-8"
    )
    assert "main-log-marker-malicious_app" not in second_experiment_log.read_text(
        encoding="utf-8"
    )
    assert "agent-log-marker-malicious_app" not in second_experiment_log.read_text(
        encoding="utf-8"
    )
    assert "agent-log-marker-malicious_app" in first_agent_log.read_text(
        encoding="utf-8"
    )
    assert "agent-log-marker-remote_attacker" not in first_agent_log.read_text(
        encoding="utf-8"
    )
    assert "agent-log-marker-remote_attacker" in second_agent_log.read_text(
        encoding="utf-8"
    )
    assert "agent-log-marker-malicious_app" not in second_agent_log.read_text(
        encoding="utf-8"
    )


def test_batch_runner_schema_matches_model():
    schema_path = REPO_ROOT / "schemas" / "batch_runner_config.schema.json"
    assert (
        schema_path.read_text(encoding="utf-8")
        == BatchRunnerConfig.render_json_schema()
    )


def test_committed_batch_config_validates_against_schema():
    schema = json.loads(
        (REPO_ROOT / "schemas" / "batch_runner_config.schema.json").read_text(
            encoding="utf-8"
        )
    )
    payload = json.loads(
        (REPO_ROOT / "runner_config_batch.json").read_text(encoding="utf-8")
    )
    payload.pop("$schema", None)
    validate(instance=payload, schema=schema)


@pytest.mark.parametrize(
    "batch_payload",
    [
        {"apps": []},
        {"apps": ["app_a", "app_a"]},
        {"apps": [""]},
        {"matrix": {}},
        {"matrix": {"bogus": ["value"]}},
        {"matrix": {"model": []}},
        {"matrix": {"app": [""]}},
        {"exclude": [{}]},
        {"exclude": [{"bogus": "value"}]},
    ],
)
def test_batch_runner_schema_rejects_runtime_invalid_batch_shapes(batch_payload):
    schema = json.loads(
        (REPO_ROOT / "schemas" / "batch_runner_config.schema.json").read_text(
            encoding="utf-8"
        )
    )
    payload = {
        **_base_payload(),
        "attacker_model": "remote_attacker",
        "batch": batch_payload,
    }

    with pytest.raises(ValidationError):
        validate(instance=payload, schema=schema)


def test_app_catalog_validates_and_sets_are_consistent():
    catalog_path = REPO_ROOT / "apps" / "app_catalog.json"
    schema = json.loads(
        (REPO_ROOT / "schemas" / "app_catalog.schema.json").read_text(encoding="utf-8")
    )
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    validate(instance=catalog, schema=schema)
    in_scope = set(catalog["sets"]["in_scope"])
    unreliable = set(catalog["sets"].get("unreliable", []))
    metadata_apps = {
        path.parent.name for path in (REPO_ROOT / "apps").glob("*/metadata.json")
    }
    assert in_scope.isdisjoint(unreliable)
    assert in_scope <= metadata_apps
    assert unreliable <= metadata_apps
    assert {"openhab", "owncloud-android", "termux"} <= in_scope
    assert unreliable == {"jitsi-meet"}
    assert "out_of_scope" not in catalog["sets"]
    assert "apps" not in catalog
    assert set(catalog.get("notes", {})) <= (in_scope | unreliable)
