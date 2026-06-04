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

The legacy synthetic-vuln path is exercised to confirm backward compatibility.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATE = REPO_ROOT / "infra" / "gke" / "generate_jobs.py"
BUILDER = REPO_ROOT / "infra" / "gke" / "build_runner_config.sh"
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


def _build_config(env: dict[str, str], base: dict, tmp_path: Path) -> dict:
    src = tmp_path / "base.json"
    src.write_text(json.dumps(base))
    dst = tmp_path / "out.json"
    run_env = dict(os.environ)
    run_env.update(env)
    subprocess.run(
        ["bash", str(BUILDER), str(src), str(dst)],
        env=run_env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(dst.read_text())


# ── generate_jobs.py: external probe-only matrix ──────────────────────────────


def test_external_probe_only_renders_full_matrix() -> None:
    """1 app x 2 attacker models x 2 no_codebase legs = 4 distinct, valid Jobs."""
    res = _generate(
        "--apps",
        "conversations",
        "--agent-image",
        AGENT_IMAGE,
        "--probe-only",
        "--attacker-models",
        "malicious_app",
        "remote_attacker",
        "--no-codebase-ablation",
        "--gcs-bucket",
        "test",
        "--dry-run",
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
        assert env["WORKFLOW"] == "redteam"
        assert env["PROBE_ONLY"] == "true"
        assert env[EMULATOR_GPU_ENV] == ""
        assert env["VULN_ID"] == ""  # unused in probe-only mode
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
        "--models",
        "gpt-4o",
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


def test_external_only_flags_rejected_on_legacy_path() -> None:
    res = _generate("--apps", "conversations", "--models", "gpt-4o", "--probe-only")
    assert res.returncode != 0
    assert "only valid with --agent-image" in res.stderr


# ── generate_jobs.py: legacy synthetic-vuln path (backward compat) ────────────


def test_legacy_path_still_renders_and_omits_external_labels() -> None:
    res = _generate(
        "--apps", "conversations", "--models", "gpt-4o", "--gcs-bucket", "t"
    )
    assert res.returncode == 0, res.stderr
    docs = [d for d in yaml.safe_load_all(res.stdout) if d]
    assert len(docs) == 1
    job = docs[0]
    env = _env_of(job)
    assert env["VULN_ID"] == "vuln_0"
    assert env["MODEL"] == "gpt-4o"
    # Most new env vars are empty so the entrypoint leaves the base config
    # untouched (backward compatible)...
    for k in ("AGENT_IMAGE", "AGENT_MODE", "WORKFLOW", "ATTACKER_MODEL"):
        assert env[k] == ""
    # ...except probe_only, which the legacy path forces false (a synthetic vuln
    # is never probe-only) so synthetic_vuln_id stays valid against RunnerConfig.
    assert env["PROBE_ONLY"] == "false"
    # Empty experiment-* labels are stripped; legacy labels remain.
    labels = job["metadata"]["labels"]
    assert labels["experiment-vuln"] == "vuln-0"
    assert "experiment-attacker" not in labels
    assert "experiment-no-codebase" not in labels


def test_legacy_requires_models() -> None:
    res = _generate("--apps", "conversations")
    assert res.returncode != 0
    assert "--models is required" in res.stderr


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
            "DRY_RUN": "true",
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


def test_builder_legacy_leaves_external_fields_untouched(tmp_path: Path) -> None:
    """Only legacy env vars set: new fields keep their base-config values."""
    cfg = _build_config(
        {"MODEL": "gpt-4o", "VULN_ID": "vuln_0", "EMULATOR_BACKEND": "container"},
        BASE_CONFIG,
        tmp_path,
    )
    assert cfg["model"] == "gpt-4o"
    assert cfg["synthetic_vuln_id"] == "vuln_0"
    # Untouched base values:
    assert cfg["agent_mode"] == "custom"
    assert cfg["workflow"] == "exploit"
    assert cfg["probe_only"] is False
    assert cfg["no_codebase"] is True
    assert cfg["agent_image"] == "cybench/mobilecybench:latest"


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


def test_committed_base_legacy_synthetic_is_valid(tmp_path: Path) -> None:
    """Regression: legacy path must not inherit probe_only=true from the base.

    End-to-end: render a real legacy job, push its env through the builder
    against the committed base, and assert the result loads. Would fail if
    build_legacy_jobs ever stopped forcing probe_only=false.
    """
    RunnerConfig = _runner_config_or_skip()
    res = _generate("--apps", "conversations", "--models", "gpt-5.5")
    assert res.returncode == 0, res.stderr
    job = [d for d in yaml.safe_load_all(res.stdout) if d][0]
    cfg = _build_config(_env_of(job), COMMITTED_BASE, tmp_path)
    cfg.pop("$schema", None)
    loaded = RunnerConfig(**cfg)
    assert loaded.probe_only is False
    assert loaded.synthetic_vuln_id == "vuln_0"
