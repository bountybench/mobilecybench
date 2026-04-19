import json
from pathlib import Path

import pytest

from utils.replay_run import (
    ReplayArtifactError,
    ReplayCompatibilityError,
    ReplayMetadataError,
    resolve_replay_run,
    stage_replay_artifact,
)


def _write_run_summary(
    path: Path,
    *,
    app_name: str = "openhab",
    workflow: str = "redteam",
    task: str | None = "report-1",
    attack_model: str | None = "malicious_app",
    outcome: str = "success",
) -> None:
    payload = {
        "run_id": "source-run-123",
        "outcome": outcome,
        "context": {"app_name": app_name, "workflow": workflow},
        "config": {
            "full_snapshot": {
                "task": task,
                "attack_model": attack_model,
            }
        },
        "results": {},
    }
    path.write_text(json.dumps(payload))


def _make_malicious_app_source(source_dir: Path) -> Path:
    agent_exploit = source_dir / "agent_exploit"
    src_dir = agent_exploit / "exploit_apk" / "src" / "com" / "mobilecybench"
    src_dir.mkdir(parents=True, exist_ok=True)
    (agent_exploit / "exploit_apk" / "AndroidManifest.xml").write_text(
        "<manifest package='com.mobilecybench.exploit' />"
    )
    (src_dir / "Exploit.java").write_text("class Exploit {}")
    return agent_exploit


def _make_auth_attacker_source(source_dir: Path) -> Path:
    agent_exploit = source_dir / "agent_exploit"
    agent_exploit.mkdir(parents=True, exist_ok=True)
    (agent_exploit / "exploit.sh").write_text("#!/bin/bash\nexit 0\n")
    return agent_exploit


class TestResolveReplayRun:
    def test_infers_metadata_and_artifact_from_source_run(self, tmp_path):
        source_dir = tmp_path / "logs" / "experiment_123"
        source_dir.mkdir(parents=True)
        _write_run_summary(source_dir / "run_summary.json", outcome="failure")
        _make_malicious_app_source(source_dir)

        spec = resolve_replay_run(
            source_dir,
            project_root=tmp_path,
            explicit_app_name=None,
            explicit_task=None,
            explicit_workflow="redteam",
            explicit_attack_model="malicious_app",
        )

        assert spec.metadata.app_name == "openhab"
        assert spec.metadata.task == "report-1"
        assert spec.metadata.workflow == "redteam"
        assert spec.metadata.attack_model == "malicious_app"
        assert spec.artifact.artifact_kind == "exploit_apk_project"
        assert any("Proceeding with replay" in warning for warning in spec.warnings)

    def test_rejects_conflicting_explicit_app(self, tmp_path):
        source_dir = tmp_path / "logs" / "experiment_123"
        source_dir.mkdir(parents=True)
        _write_run_summary(source_dir / "run_summary.json", app_name="openhab")
        _make_auth_attacker_source(source_dir)

        with pytest.raises(ReplayCompatibilityError, match="source run app"):
            resolve_replay_run(
                source_dir,
                project_root=tmp_path,
                explicit_app_name="wallabag",
                explicit_task="report-1",
                explicit_workflow="redteam",
                explicit_attack_model="auth_attacker",
            )

    def test_requires_agent_exploit_directory(self, tmp_path):
        source_dir = tmp_path / "logs" / "experiment_123"
        source_dir.mkdir(parents=True)
        _write_run_summary(source_dir / "run_summary.json")

        with pytest.raises(ReplayArtifactError, match="agent submitted an exploit"):
            resolve_replay_run(
                source_dir,
                project_root=tmp_path,
                explicit_app_name="openhab",
                explicit_task="report-1",
                explicit_workflow="redteam",
                explicit_attack_model="malicious_app",
            )

    def test_requires_task_when_metadata_missing(self, tmp_path):
        source_dir = tmp_path / "logs" / "experiment_123"
        source_dir.mkdir(parents=True)
        _write_run_summary(
            source_dir / "run_summary.json",
            task=None,
            attack_model="auth_attacker",
        )
        _make_auth_attacker_source(source_dir)

        with pytest.raises(ReplayMetadataError, match="could not determine redteam task"):
            resolve_replay_run(
                source_dir,
                project_root=tmp_path,
                explicit_app_name="openhab",
                explicit_task=None,
                explicit_workflow="redteam",
                explicit_attack_model="auth_attacker",
            )


class TestStageReplayArtifact:
    def test_injects_canonical_build_script_for_malicious_app(self, tmp_path):
        source_dir = tmp_path / "logs" / "experiment_123"
        source_dir.mkdir(parents=True)
        _write_run_summary(source_dir / "run_summary.json")
        _make_malicious_app_source(source_dir)

        project_root = tmp_path / "project"
        build_script = (
            project_root / "templates" / "malicious_app" / "build_exploit_apk.sh"
        )
        build_script.parent.mkdir(parents=True, exist_ok=True)
        build_script.write_text("#!/bin/bash\necho canonical\n")

        spec = resolve_replay_run(
            source_dir,
            project_root=tmp_path,
            explicit_app_name="openhab",
            explicit_task="report-1",
            explicit_workflow="redteam",
            explicit_attack_model="malicious_app",
        )

        logs_dir = tmp_path / "current_logs"
        logs_dir.mkdir()
        target_dir, replay_source_path = stage_replay_artifact(
            spec,
            logs_dir=logs_dir,
            project_root=project_root,
        )

        injected_script = target_dir / "exploit_apk" / "build_exploit_apk.sh"
        assert injected_script.exists()
        assert injected_script.read_text() == build_script.read_text()
        assert replay_source_path.exists()
        record = json.loads(replay_source_path.read_text())
        assert record["mode"] == "replay_run"
        assert record["source_app"] == "openhab"

    def test_preserves_auth_attacker_exploit(self, tmp_path):
        source_dir = tmp_path / "logs" / "experiment_123"
        source_dir.mkdir(parents=True)
        _write_run_summary(
            source_dir / "run_summary.json",
            attack_model="auth_attacker",
        )
        _make_auth_attacker_source(source_dir)

        project_root = tmp_path / "project"
        (project_root / "templates" / "malicious_app").mkdir(parents=True, exist_ok=True)

        spec = resolve_replay_run(
            source_dir,
            project_root=tmp_path,
            explicit_app_name="openhab",
            explicit_task="report-1",
            explicit_workflow="redteam",
            explicit_attack_model="auth_attacker",
        )

        logs_dir = tmp_path / "current_logs"
        logs_dir.mkdir()
        target_dir, _ = stage_replay_artifact(
            spec,
            logs_dir=logs_dir,
            project_root=project_root,
        )

        assert (target_dir / "exploit.sh").exists()
