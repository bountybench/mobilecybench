"""Behavior tests for replay-run resolution and staging.

Assertions are on observable outcomes (returned fields, files on disk,
error messages) — not on internal helpers or exception subclasses.
"""

import json
from pathlib import Path

import pytest

from utils.replay_run import (
    ReplayRunError,
    load_replay_source,
    stage_replay_exploit,
)


def _write_run_summary(
    path: Path,
    *,
    app_name: str | None = "openhab",
    workflow: str | None = "redteam",
    task: str | None = "report-1",
    attack_model: str | None = "malicious_app",
) -> None:
    payload = {
        "context": {"app_name": app_name, "workflow": workflow},
        "config": {"full_snapshot": {"task": task, "attack_model": attack_model}},
    }
    path.write_text(json.dumps(payload))


def _write_malicious_exploit(source_dir: Path) -> None:
    apk = source_dir / "agent_exploit" / "exploit_apk"
    (apk / "src" / "com" / "exploit").mkdir(parents=True)
    (apk / "AndroidManifest.xml").write_text("<manifest/>")
    (apk / "src" / "com" / "exploit" / "E.java").write_text("class E{}")


def _write_auth_exploit(source_dir: Path) -> None:
    d = source_dir / "agent_exploit"
    d.mkdir(parents=True)
    (d / "exploit.sh").write_text("#!/bin/bash\nexit 0\n")


# ---------------------------------------------------------------------------
# load_replay_source
# ---------------------------------------------------------------------------


class TestLoadReplaySource:
    def test_returns_fields_from_run_summary(self, tmp_path):
        src = tmp_path / "logs" / "experiment_1"
        src.mkdir(parents=True)
        _write_run_summary(src / "run_summary.json")
        _write_malicious_exploit(src)

        spec = load_replay_source(str(src), tmp_path)

        assert spec.app_name == "openhab"
        assert spec.task == "report-1"
        assert spec.attack_model == "malicious_app"
        assert spec.source_dir == src.resolve()

    def test_resolves_path_relative_to_project_root(self, tmp_path):
        src = tmp_path / "logs" / "experiment_1"
        src.mkdir(parents=True)
        _write_run_summary(src / "run_summary.json")
        _write_malicious_exploit(src)

        spec = load_replay_source("logs/experiment_1", tmp_path)
        assert spec.source_dir == src.resolve()

    def test_missing_source_dir(self, tmp_path):
        with pytest.raises(ReplayRunError, match="not found"):
            load_replay_source("nope", tmp_path)

    def test_source_is_file_not_dir(self, tmp_path):
        f = tmp_path / "x"
        f.write_text("")
        with pytest.raises(ReplayRunError, match="not a directory"):
            load_replay_source(str(f), tmp_path)

    def test_missing_run_summary(self, tmp_path):
        src = tmp_path / "logs" / "experiment_1"
        src.mkdir(parents=True)
        with pytest.raises(ReplayRunError, match="run_summary.json"):
            load_replay_source(str(src), tmp_path)

    def test_malformed_run_summary(self, tmp_path):
        src = tmp_path / "logs" / "experiment_1"
        src.mkdir(parents=True)
        (src / "run_summary.json").write_text("{not json")
        with pytest.raises(ReplayRunError, match="malformed"):
            load_replay_source(str(src), tmp_path)

    def test_rejects_non_redteam_workflow(self, tmp_path):
        src = tmp_path / "logs" / "experiment_1"
        src.mkdir(parents=True)
        _write_run_summary(src / "run_summary.json", workflow="exploit")
        with pytest.raises(ReplayRunError, match="only 'redteam'"):
            load_replay_source(str(src), tmp_path)

    @pytest.mark.parametrize(
        "missing_kwarg,expected",
        [
            ({"app_name": None}, "app_name"),
            ({"task": None}, "task"),
            ({"attack_model": None}, "attack_model"),
        ],
    )
    def test_missing_required_field(self, tmp_path, missing_kwarg, expected):
        src = tmp_path / "logs" / "experiment_1"
        src.mkdir(parents=True)
        _write_run_summary(src / "run_summary.json", **missing_kwarg)
        _write_malicious_exploit(src)
        with pytest.raises(ReplayRunError, match=expected):
            load_replay_source(str(src), tmp_path)

    def test_missing_agent_exploit_dir(self, tmp_path):
        src = tmp_path / "logs" / "experiment_1"
        src.mkdir(parents=True)
        _write_run_summary(src / "run_summary.json")
        with pytest.raises(ReplayRunError, match="No agent_exploit"):
            load_replay_source(str(src), tmp_path)

    def test_malicious_app_missing_manifest(self, tmp_path):
        src = tmp_path / "logs" / "experiment_1"
        src.mkdir(parents=True)
        _write_run_summary(src / "run_summary.json")
        (src / "agent_exploit" / "exploit_apk").mkdir(parents=True)
        with pytest.raises(ReplayRunError, match="AndroidManifest"):
            load_replay_source(str(src), tmp_path)

    def test_malicious_app_missing_java_sources(self, tmp_path):
        src = tmp_path / "logs" / "experiment_1"
        src.mkdir(parents=True)
        _write_run_summary(src / "run_summary.json")
        apk = src / "agent_exploit" / "exploit_apk"
        apk.mkdir(parents=True)
        (apk / "AndroidManifest.xml").write_text("<manifest/>")
        with pytest.raises(ReplayRunError, match="Java sources"):
            load_replay_source(str(src), tmp_path)

    def test_auth_attacker_missing_exploit_sh(self, tmp_path):
        src = tmp_path / "logs" / "experiment_1"
        src.mkdir(parents=True)
        _write_run_summary(src / "run_summary.json", attack_model="auth_attacker")
        (src / "agent_exploit").mkdir()
        with pytest.raises(ReplayRunError, match="exploit.sh"):
            load_replay_source(str(src), tmp_path)

    def test_auth_attacker_happy_path(self, tmp_path):
        src = tmp_path / "logs" / "experiment_1"
        src.mkdir(parents=True)
        _write_run_summary(src / "run_summary.json", attack_model="auth_attacker")
        _write_auth_exploit(src)

        spec = load_replay_source(str(src), tmp_path)
        assert spec.attack_model == "auth_attacker"


# ---------------------------------------------------------------------------
# stage_replay_exploit
# ---------------------------------------------------------------------------


class TestStageReplayExploit:
    def test_malicious_app_injects_canonical_build_script(self, tmp_path):
        src = tmp_path / "logs" / "experiment_1"
        src.mkdir(parents=True)
        _write_run_summary(src / "run_summary.json")
        _write_malicious_exploit(src)

        project = tmp_path / "proj"
        script = project / "templates" / "malicious_app" / "build_exploit_apk.sh"
        script.parent.mkdir(parents=True)
        script.write_text("#!/bin/bash\necho canonical\n")

        spec = load_replay_source(str(src), tmp_path)
        logs = tmp_path / "current"
        logs.mkdir()
        target = stage_replay_exploit(spec, logs_dir=logs, project_root=project)

        injected = target / "exploit_apk" / "build_exploit_apk.sh"
        assert injected.read_text() == script.read_text()
        assert injected.stat().st_mode & 0o111  # executable

    def test_auth_attacker_marks_exploit_executable(self, tmp_path):
        src = tmp_path / "logs" / "experiment_1"
        src.mkdir(parents=True)
        _write_run_summary(src / "run_summary.json", attack_model="auth_attacker")
        _write_auth_exploit(src)

        spec = load_replay_source(str(src), tmp_path)
        logs = tmp_path / "current"
        logs.mkdir()
        target = stage_replay_exploit(
            spec, logs_dir=logs, project_root=tmp_path / "proj"
        )
        assert (target / "exploit.sh").stat().st_mode & 0o111

    def test_replaces_existing_target(self, tmp_path):
        src = tmp_path / "logs" / "experiment_1"
        src.mkdir(parents=True)
        _write_run_summary(src / "run_summary.json", attack_model="auth_attacker")
        _write_auth_exploit(src)

        logs = tmp_path / "current"
        logs.mkdir()
        stale = logs / "agent_exploit"
        stale.mkdir()
        (stale / "stale.txt").write_text("old")

        spec = load_replay_source(str(src), tmp_path)
        target = stage_replay_exploit(
            spec, logs_dir=logs, project_root=tmp_path / "proj"
        )
        assert not (target / "stale.txt").exists()
        assert (target / "exploit.sh").exists()

    def test_missing_canonical_build_script(self, tmp_path):
        src = tmp_path / "logs" / "experiment_1"
        src.mkdir(parents=True)
        _write_run_summary(src / "run_summary.json")
        _write_malicious_exploit(src)

        spec = load_replay_source(str(src), tmp_path)
        logs = tmp_path / "current"
        logs.mkdir()
        with pytest.raises(ReplayRunError, match="build script"):
            stage_replay_exploit(spec, logs_dir=logs, project_root=tmp_path / "proj")
