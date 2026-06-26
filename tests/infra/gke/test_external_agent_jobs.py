"""Tests for the GKE external-agent / probe-only job path.

Covers the two pieces wired up for running BYO coding-agent images over the
redteam probe-only workflow with an attacker-model x source-vs-APK matrix:

  * generate_jobs.py renders one valid K8s Job per
    (app x attacker_model x no_codebase leg), plumbing the external fields
    into the Job env without requiring a synthetic vuln.
  * build_runner_config.sh layers those env vars onto the base config to
    produce a runner_config.json with agent_mode=external, workflow=redteam,
    probe_only=true, the right attacker_model / no_codebase, and no
    synthetic_vuln_id.
  * GKE smoke configs no longer depend on synthetic VULN_ID values.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATE = REPO_ROOT / "infra" / "gke" / "generate_jobs.py"
BUILDER = REPO_ROOT / "infra" / "gke" / "build_runner_config.sh"
APP_CATALOG = REPO_ROOT / "apps" / "app_catalog.json"
TEST_LOCAL = REPO_ROOT / "infra" / "gke" / "test_local.sh"
TEST_GKE = REPO_ROOT / "infra" / "gke" / "test_gke.sh"
BUILD_AND_PUSH = REPO_ROOT / "infra" / "gke" / "build_and_push.sh"
DRYRUN_CONFIG = REPO_ROOT / "infra" / "gke" / "runner_config_container_dryrun.json"
EMULATOR_GPU_ENV = "MOBILECYBENCH_EMULATOR_GPU"

# A base config whose bundle selectors are populated, so probe-only's
# clear-to-null behavior is observable.
BASE_CONFIG = {
    "$schema": "./schemas/runner_config.schema.json",
    "workflow": "exploit",
    "probe_only": False,
    "attacker_model": None,
    "task": "some-task",
    "synthetic_vuln_id": "vuln_9",
    "no_codebase": True,
    "agent_mode": "custom",
    "model": "gpt-5.5",
    "agent_image": "cybench/mobilecybench:latest",
    "build_type": "download-apk",
    "emulator_backend": "native",
    "emulator_display": "headed",
    "network_mode": "permissive",
    "dry_run": False,
    "gold_run": False,
}

AGENT_IMAGE = "cybench/mobilecybench:opencode_1.15.6-r1"
MODEL = "openai/gpt-5.5"


def _generate(
    *argv: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    run_env = dict(os.environ)
    run_env.pop(EMULATOR_GPU_ENV, None)
    if env:
        run_env.update(env)
    return subprocess.run(
        [sys.executable, str(GENERATE), *argv],
        env=run_env,
        capture_output=True,
        text=True,
    )


def _env_of(job: dict) -> dict[str, str]:
    container = job["spec"]["template"]["spec"]["containers"][0]
    return {
        e["name"]: str(e.get("value", "")) for e in container["env"] if "value" in e
    }


def _run_builder(
    env: dict[str, str], base: dict, tmp_path: Path
) -> tuple[subprocess.CompletedProcess, Path]:
    src = tmp_path / "base.json"
    src.write_text(json.dumps(base))
    dst = tmp_path / "out.json"
    run_env = dict(os.environ)
    run_env.update(env)
    result = subprocess.run(
        ["bash", str(BUILDER), str(src), str(dst)],
        env=run_env,
        capture_output=True,
        text=True,
    )
    return result, dst


def _build_config(env: dict[str, str], base: dict, tmp_path: Path) -> dict:
    result, dst = _run_builder(env, base, tmp_path)
    assert result.returncode == 0, result.stderr
    return json.loads(dst.read_text())


# ── generate_jobs.py: external probe-only matrix ──────────────────────────────


def test_external_probe_only_renders_full_matrix() -> None:
    """1 app x 2 attacker models x 2 no_codebase legs = 4 distinct, valid Jobs."""
    res = _generate(
        "--apps",
        "conversations",
        "--agent-image",
        AGENT_IMAGE,
        "--models",
        MODEL,
        "--probe-only",
        "--attacker-models",
        "malicious_app",
        "remote_attacker",
        "--no-codebase-ablation",
        "--gcs-bucket",
        "test",
    )
    assert res.returncode == 0, res.stderr
    docs = [d for d in yaml.safe_load_all(res.stdout) if d]

    assert len(docs) == 4
    assert all(d["kind"] == "Job" for d in docs)
    assert len({d["metadata"]["name"] for d in docs}) == 4

    combos = set()
    for d in docs:
        env = _env_of(d)
        assert env["AGENT_MODE"] == "external"
        assert env["AGENT_IMAGE"] == AGENT_IMAGE
        assert env["MODEL"] == MODEL
        assert env["WORKFLOW"] == "redteam"
        assert env["PROBE_ONLY"] == "true"
        assert env[EMULATOR_GPU_ENV] == ""
        assert "VULN_ID" not in env
        # The agent image is plumbed via runner_config, NOT as the pod image.
        assert d["spec"]["template"]["spec"]["containers"][0]["image"] != AGENT_IMAGE
        combos.add((env["ATTACKER_MODEL"], env["NO_CODEBASE"]))

    assert combos == {
        ("malicious_app", "true"),
        ("malicious_app", "false"),
        ("remote_attacker", "true"),
        ("remote_attacker", "false"),
    }


def test_external_without_ablation_is_single_leg() -> None:
    res = _generate(
        "--apps",
        "conversations",
        "--agent-image",
        AGENT_IMAGE,
        "--probe-only",
        "--attacker-models",
        "malicious_app",
        "--gcs-bucket",
        "test",
    )
    assert res.returncode == 0, res.stderr
    docs = [d for d in yaml.safe_load_all(res.stdout) if d]
    assert len(docs) == 1
    assert _env_of(docs[0])["NO_CODEBASE"] == "false"


def test_all_uses_active_app_catalog() -> None:
    catalog_apps = json.loads(APP_CATALOG.read_text())["sets"]["in_scope"]
    res = _generate(
        "--all",
        "--agent-image",
        AGENT_IMAGE,
        "--probe-only",
        "--attacker-models",
        "malicious_app",
        "--gcs-bucket",
        "test",
    )
    assert res.returncode == 0, res.stderr
    docs = [d for d in yaml.safe_load_all(res.stdout) if d]

    assert len(docs) == len(catalog_apps)
    assert [_env_of(d)["APP_NAME"] for d in docs] == catalog_apps


def test_discover_apps_uses_catalog_not_directory_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from infra.gke import generate_jobs

    apps_dir = tmp_path / "apps"
    (apps_dir / "catalog-app").mkdir(parents=True)
    (apps_dir / "directory-only-app").mkdir()
    monkeypatch.setattr(generate_jobs, "load_active_apps", lambda: ["catalog-app"])

    assert generate_jobs.discover_apps(apps_dir, None) == ["catalog-app"]
    with pytest.raises(SystemExit):
        generate_jobs.discover_apps(apps_dir, ["directory-only-app"])
    assert "unknown or archived app(s): directory-only-app" in capsys.readouterr().err


def test_non_catalog_app_is_rejected() -> None:
    res = _generate(
        "--apps",
        "archived-demo-app",
        "--agent-image",
        AGENT_IMAGE,
        "--probe-only",
        "--attacker-models",
        "malicious_app",
        "--gcs-bucket",
        "test",
    )
    assert res.returncode != 0
    assert "unknown or archived app(s): archived-demo-app" in res.stderr


def test_emulator_gpu_env_is_plumbed_to_jobs() -> None:
    res = _generate(
        "--apps",
        "conversations",
        "--agent-image",
        AGENT_IMAGE,
        "--probe-only",
        "--attacker-models",
        "malicious_app",
        "--gcs-bucket",
        "test",
        env={EMULATOR_GPU_ENV: "swangle"},
    )
    assert res.returncode == 0, res.stderr
    docs = [d for d in yaml.safe_load_all(res.stdout) if d]

    assert _env_of(docs[0])[EMULATOR_GPU_ENV] == "swangle"


def test_emulator_gpu_cli_is_plumbed_to_jobs() -> None:
    res = _generate(
        "--apps",
        "conversations",
        "--agent-image",
        AGENT_IMAGE,
        "--probe-only",
        "--attacker-models",
        "malicious_app",
        "--gcs-bucket",
        "test",
        "--emulator-gpu",
        "swangle",
    )
    assert res.returncode == 0, res.stderr
    docs = [d for d in yaml.safe_load_all(res.stdout) if d]

    assert _env_of(docs[0])[EMULATOR_GPU_ENV] == "swangle"


def test_external_requires_attacker_models() -> None:
    res = _generate("--apps", "conversations", "--agent-image", AGENT_IMAGE)
    assert res.returncode != 0
    assert "--attacker-models is required" in res.stderr


def test_generate_requires_agent_image() -> None:
    res = _generate(
        "--apps",
        "conversations",
        "--models",
        MODEL,
        "--probe-only",
        "--attacker-models",
        "malicious_app",
    )
    assert res.returncode != 0
    assert "--agent-image" in res.stderr


def test_generate_requires_probe_only() -> None:
    res = _generate(
        "--apps",
        "conversations",
        "--agent-image",
        AGENT_IMAGE,
        "--attacker-models",
        "malicious_app",
    )
    assert res.returncode != 0
    assert "--probe-only is required" in res.stderr


@pytest.mark.parametrize("flag", ["--dry-run", "--gold-run"])
def test_generate_rejects_probe_only_dry_or_gold_run(flag: str) -> None:
    res = _generate(
        "--apps",
        "conversations",
        "--agent-image",
        AGENT_IMAGE,
        "--probe-only",
        "--attacker-models",
        "malicious_app",
        flag,
    )
    assert res.returncode != 0
    assert f"--probe-only cannot be combined with {flag}" in res.stderr


# ── build_runner_config.sh: env -> runner_config.json ─────────────────────────


@pytest.mark.parametrize("no_codebase", ["true", "false"])
def test_builder_external_probe_only(tmp_path: Path, no_codebase: str) -> None:
    cfg = _build_config(
        {
            "AGENT_MODE": "external",
            "AGENT_IMAGE": AGENT_IMAGE,
            "WORKFLOW": "redteam",
            "PROBE_ONLY": "true",
            "ATTACKER_MODEL": "remote_attacker",
            "NO_CODEBASE": no_codebase,
            "EMULATOR_BACKEND": "container",
            "AGENT_WALLCLOCK_SECONDS": "1800",
            "MODEL": "",
            "VULN_ID": "",
            "DRY_RUN": "false",
        },
        BASE_CONFIG,
        tmp_path,
    )
    assert cfg["agent_mode"] == "external"
    assert cfg["workflow"] == "redteam"
    assert cfg["probe_only"] is True
    assert cfg["attacker_model"] == "remote_attacker"
    assert cfg["no_codebase"] is (no_codebase == "true")
    assert cfg["agent_image"] == AGENT_IMAGE
    assert cfg["emulator_backend"] == "container"
    assert cfg["agent_wallclock_seconds"] == 1800
    # probe-only is bundle-less: selectors must be cleared regardless of base.
    assert cfg["synthetic_vuln_id"] is None
    assert cfg["task"] is None
    # model not overridden -> base value retained.
    assert cfg["model"] == "gpt-5.5"


def test_builder_rejects_retired_vuln_id(tmp_path: Path) -> None:
    result, dst = _run_builder(
        {"MODEL": MODEL, "VULN_ID": "vuln_0", "EMULATOR_BACKEND": "container"},
        BASE_CONFIG,
        tmp_path,
    )
    assert result.returncode != 0
    assert "VULN_ID is retired for GKE jobs" in result.stderr
    assert not dst.exists() or dst.read_text() == ""


@pytest.mark.parametrize("mode_flag", ["DRY_RUN", "GOLD_RUN"])
def test_builder_rejects_probe_only_dry_or_gold_run(
    tmp_path: Path, mode_flag: str
) -> None:
    result, _ = _run_builder(
        {
            "AGENT_MODE": "external",
            "WORKFLOW": "redteam",
            "PROBE_ONLY": "true",
            "ATTACKER_MODEL": "remote_attacker",
            mode_flag: "true",
        },
        BASE_CONFIG,
        tmp_path,
    )
    assert result.returncode != 0
    assert "PROBE_ONLY is incompatible with DRY_RUN/GOLD_RUN" in result.stderr


def test_builder_clears_base_synthetic_id(tmp_path: Path) -> None:
    cfg = _build_config({"EMULATOR_BACKEND": "container"}, BASE_CONFIG, tmp_path)
    assert cfg["synthetic_vuln_id"] is None


def test_builder_no_codebase_false_is_written_not_skipped(tmp_path: Path) -> None:
    """NO_CODEBASE='false' must override base (true) -> distinguishes unset from false."""
    cfg = _build_config({"NO_CODEBASE": "false"}, BASE_CONFIG, tmp_path)
    assert cfg["no_codebase"] is False


# ── end-to-end: built config validates against the real RunnerConfig ──────────
# These feed the *committed* runner_config.json (the actual CONFIG_SRC in the
# image) through the builder and assert the result loads, which is the invariant
# that ultimately matters: a job that renders but fails RunnerConfig at load
# wastes an image pull + emulator boot in-cluster.

COMMITTED_BASE = json.loads((REPO_ROOT / "runner_config.json").read_text())


def _runner_config_or_skip():
    config = pytest.importorskip("models.config")
    return config.RunnerConfig


@pytest.mark.parametrize("no_codebase", ["true", "false"])
def test_committed_base_external_probe_only_is_valid(
    tmp_path: Path, no_codebase: str
) -> None:
    RunnerConfig = _runner_config_or_skip()
    cfg = _build_config(
        {
            "AGENT_MODE": "external",
            "AGENT_IMAGE": AGENT_IMAGE,
            "WORKFLOW": "redteam",
            "PROBE_ONLY": "true",
            "ATTACKER_MODEL": "remote_attacker",
            "NO_CODEBASE": no_codebase,
            "EMULATOR_BACKEND": "container",
            "AGENT_WALLCLOCK_SECONDS": "1800",
            "MODEL": "",
            "VULN_ID": "",
            "DRY_RUN": "false",  # probe_only forbids dry_run
        },
        COMMITTED_BASE,
        tmp_path,
    )
    cfg.pop("$schema", None)
    RunnerConfig(**cfg)  # raises if invalid


def test_committed_container_config_is_probe_only_redteam() -> None:
    cfg = json.loads(DRYRUN_CONFIG.read_text())
    assert cfg["workflow"] == "redteam"
    assert cfg["probe_only"] is True
    assert cfg["task"] is None
    assert cfg["synthetic_vuln_id"] is None
    assert cfg["dry_run"] is False


def test_committed_container_config_is_valid() -> None:
    RunnerConfig = _runner_config_or_skip()
    cfg = json.loads(DRYRUN_CONFIG.read_text())
    cfg.pop("$schema", None)
    RunnerConfig(**cfg)  # raises if invalid


def test_test_local_config_is_probe_only_redteam() -> None:
    text = TEST_LOCAL.read_text()
    assert 'ATTACKER_MODEL="${ATTACKER_MODEL:-remote_attacker}"' in text
    assert '"workflow": "redteam"' in text
    assert '"probe_only": true' in text
    assert '"attacker_model": "$ATTACKER_MODEL"' in text
    assert '"synthetic_vuln_id"' not in text
    assert "VULN_ID" not in text


def test_test_gke_manifest_has_no_retired_vuln_id() -> None:
    text = TEST_GKE.read_text()
    assert "VULN_ID" not in text
    assert "vuln_0" not in text
    assert "name: WORKFLOW" in text
    assert "name: PROBE_ONLY" in text


@pytest.mark.parametrize(
    ("script", "argv"),
    [
        (TEST_LOCAL, ["--dry-run"]),
        (TEST_LOCAL, ["--gold-run"]),
        (TEST_LOCAL, ["--vuln", "vuln_0"]),
        (TEST_GKE, ["--dry-run"]),
        (TEST_GKE, ["--gold-run"]),
    ],
)
def test_smoke_scripts_reject_retired_or_incompatible_modes(
    script: Path, argv: list[str]
) -> None:
    result = subprocess.run(
        ["bash", str(script), *argv],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "ERROR:" in result.stdout


def test_build_and_push_uses_active_catalog_and_clean_apks_only(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    script = repo / "infra" / "gke" / "build_and_push.sh"
    script.parent.mkdir(parents=True)
    shutil.copy2(BUILD_AND_PUSH, script)

    apps_dir = repo / "apps"
    for app in ("catalog-one", "catalog-two", "directory-only"):
        (apps_dir / app).mkdir(parents=True)
    (apps_dir / "directory-only" / "synthetic_vulnerabilities" / "vuln_0").mkdir(
        parents=True
    )
    (apps_dir / "app_catalog.json").write_text(
        json.dumps({"sets": {"in_scope": ["catalog-one", "catalog-two"]}})
    )

    log = tmp_path / "commands.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").write_text(
        "#!/usr/bin/env bash\n"
        f'echo git "$@" >> {log}\n'
        'if [ "$1" = config ]; then\n'
        "  echo submodule.apps/catalog-one/codebase.path apps/catalog-one/codebase\n"
        "  echo submodule.apps/directory-only/codebase.path apps/directory-only/codebase\n"
        "fi\n"
    )
    (bin_dir / "docker").write_text(
        "#!/usr/bin/env bash\n" f'echo docker "$@" >> {log}\n'
    )
    (bin_dir / "git").chmod(0o755)
    (bin_dir / "docker").chmod(0o755)

    env = {
        **os.environ,
        "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
    }
    result = subprocess.run(
        ["bash", str(script)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Found active apps:" in result.stdout
    assert "catalog-one" in result.stdout
    assert "catalog-two" in result.stdout
    assert "directory-only" not in result.stdout

    commands = log.read_text()
    assert "apps/catalog-one/codebase" in commands
    assert "apps/directory-only/codebase" not in commands
    assert "./build_apk.sh catalog-one" in commands
    assert "./build_apk.sh catalog-two" in commands
    assert "--vuln" not in commands
