"""Tests for the GKE external-agent / probe-only job path.

These cover the pieces wired up for running BYO coding-agent images over the
redteam probe-only workflow:

  * generate_jobs.py renders valid K8s Jobs with the external-agent fields,
    APK/no-codebase controls, attacker-model matrix, and wall-clock budget.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATE = REPO_ROOT / "infra" / "gke" / "generate_jobs.py"
_SPEC = importlib.util.spec_from_file_location("generate_jobs", GENERATE)
assert _SPEC and _SPEC.loader
generate_jobs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(generate_jobs)

AGENT_IMAGE = "cybench/mobilecybench:opencode_1.15.6-r1"


def _generate(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GENERATE), *argv],
        capture_output=True,
        text=True,
    )


def _env_of(job: dict) -> dict[str, str]:
    container = job["spec"]["template"]["spec"]["containers"][0]
    return {
        e["name"]: str(e.get("value", "")) for e in container["env"] if "value" in e
    }


def test_probe_only_external_job_renders_wallclock_and_agent_fields() -> None:
    res = _generate(
        "--apps",
        "wallabag",
        "--models",
        "claude-opus-4-7",
        "--probe-only",
        "--attacker-model",
        "malicious_app",
        "--agent-mode",
        "external",
        "--agent-image",
        AGENT_IMAGE,
        "--agent-wallclock-seconds",
        "7200",
        "--reasoning-effort",
        "xhigh",
        "--no-codebase",
        "--apk-obfuscation",
        "on",
        "--gcs-bucket",
        "test-bucket",
    )
    assert res.returncode == 0, res.stderr
    docs = [d for d in yaml.safe_load_all(res.stdout) if d]
    assert len(docs) == 1
    env = _env_of(docs[0])
    assert env["AGENT_MODE"] == "external"
    assert env["AGENT_IMAGE"] == AGENT_IMAGE
    assert env["PROBE_ONLY"] == "true"
    assert env["ATTACKER_MODEL"] == "malicious_app"
    assert env["NO_CODEBASE"] == "true"
    assert env["NETWORK_MODE"] == "restricted"
    assert env["REASONING_EFFORT"] == "xhigh"
    assert env["AGENT_WALLCLOCK_SECONDS"] == "7200"
    assert env["ADDITIONAL_SYSTEM_PROMPT"] == ""


def test_external_jobs_require_agent_image_even_without_probe_matrix() -> None:
    res = _generate(
        "--apps",
        "wallabag",
        "--models",
        "gpt-5.5",
        "--agent-mode",
        "external",
    )
    assert res.returncode == 1
    assert "--agent-image is required for --agent-mode external jobs" in res.stderr


def test_probe_only_external_job_carries_additional_system_prompt() -> None:
    prompt = 'Keep exploring "distinct" vulnerabilities.\nDo not stop after the first plausible finding.'
    res = _generate(
        "--apps",
        "wallabag",
        "--models",
        "claude-opus-4-7",
        "--probe-only",
        "--attacker-model",
        "malicious_app",
        "--agent-mode",
        "external",
        "--agent-image",
        AGENT_IMAGE,
        "--additional-system-prompt",
        prompt,
        "--gcs-bucket",
        "test-bucket",
    )
    assert res.returncode == 0, res.stderr
    docs = [d for d in yaml.safe_load_all(res.stdout) if d]
    assert len(docs) == 1
    env = _env_of(docs[0])
    assert env["ADDITIONAL_SYSTEM_PROMPT"] == prompt


def test_provider_prefixed_model_rejected_before_job_submission() -> None:
    res = _generate(
        "--apps",
        "wallabag",
        "--models",
        "openai/gpt-5.5",
        "--probe-only",
        "--attacker-model",
        "malicious_app",
        "--agent-mode",
        "external",
        "--agent-image",
        AGENT_IMAGE,
        "--gcs-bucket",
        "test-bucket",
    )
    assert res.returncode == 1
    assert "Provider-prefixed model ids are not valid runner models" in res.stderr


def test_probe_only_external_ablation_renders_source_and_apk_legs() -> None:
    res = _generate(
        "--apps",
        "wallabag",
        "--models",
        "claude-opus-4-7",
        "--probe-only",
        "--attacker-models",
        "malicious_app",
        "remote_attacker",
        "--agent-mode",
        "external",
        "--agent-image",
        AGENT_IMAGE,
        "--agent-wallclock-seconds",
        "7200",
        "--reasoning-effort",
        "xhigh",
        "--no-codebase-ablation",
        "--apk-obfuscation",
        "on",
        "--gcs-bucket",
        "test-bucket",
    )
    assert res.returncode == 0, res.stderr
    docs = [d for d in yaml.safe_load_all(res.stdout) if d]
    assert len(docs) == 4
    envs = [_env_of(doc) for doc in docs]
    assert sorted(
        (
            e["ATTACKER_MODEL"],
            e["NO_CODEBASE"],
            e["APK_OBFUSCATION"],
            e["NETWORK_MODE"],
        )
        for e in envs
    ) == [
        ("malicious_app", "false", "off", ""),
        ("malicious_app", "true", "on", "restricted"),
        ("remote_attacker", "false", "off", ""),
        ("remote_attacker", "true", "on", "restricted"),
    ]


def test_probe_only_custom_attacker_matrix_renders_two_jobs() -> None:
    res = _generate(
        "--apps",
        "wallabag",
        "--models",
        "gpt-5.5",
        "--probe-only",
        "--attacker-models",
        "malicious_app",
        "remote_attacker",
        "--agent-mode",
        "custom",
        "--no-codebase",
        "--apk-obfuscation",
        "on",
        "--gcs-bucket",
        "test-bucket",
    )
    assert res.returncode == 0, res.stderr
    docs = [d for d in yaml.safe_load_all(res.stdout) if d]
    assert len(docs) == 2
    envs = [_env_of(doc) for doc in docs]
    assert sorted(
        (e["ATTACKER_MODEL"], e["AGENT_MODE"], e["NO_CODEBASE"], e["NETWORK_MODE"])
        for e in envs
    ) == [
        ("malicious_app", "custom", "true", "restricted"),
        ("remote_attacker", "custom", "true", "restricted"),
    ]


def test_no_codebase_ablation_rejected_outside_probe_only() -> None:
    res = _generate(
        "--apps",
        "wallabag",
        "--models",
        "gpt-5.5",
        "--no-codebase-ablation",
    )
    assert res.returncode == 1
    assert "--no-codebase-ablation is only valid with --probe-only" in res.stderr


def test_obfuscated_jobs_reject_permissive_network_mode() -> None:
    res = _generate(
        "--apps",
        "wallabag",
        "--models",
        "gpt-5.5",
        "--probe-only",
        "--agent-mode",
        "external",
        "--agent-image",
        AGENT_IMAGE,
        "--no-codebase",
        "--apk-obfuscation",
        "on",
        "--network-mode",
        "permissive",
    )
    assert res.returncode == 1
    assert "--apk-obfuscation on requires --network-mode restricted" in res.stderr


def test_gke_evidence_controls_render_into_job_yaml() -> None:
    res = _generate(
        "--apps",
        "wallabag",
        "--models",
        "gpt-5.4",
        "--probe-only",
        "--attacker-model",
        "remote_attacker",
        "--agent-mode",
        "custom",
        "--no-codebase",
        "--apk-obfuscation",
        "on",
        "--backoff-limit",
        "0",
        "--ttl-seconds-after-finished",
        "604800",
        "--upload-failure-hold-seconds",
        "21600",
        "--require-gcs-auth-preflight",
    )
    assert res.returncode == 0, res.stderr
    docs = [d for d in yaml.safe_load_all(res.stdout) if d]
    assert len(docs) == 1
    job = docs[0]
    env = _env_of(job)

    assert job["spec"]["backoffLimit"] == 0
    assert job["spec"]["ttlSecondsAfterFinished"] == 604800
    assert env["UPLOAD_FAILURE_HOLD_SECONDS"] == "21600"
    assert env["REQUIRE_GCS_AUTH_PREFLIGHT"] == "true"


def test_negative_backoff_limit_rejected() -> None:
    res = _generate(
        "--apps",
        "wallabag",
        "--models",
        "gpt-5.4",
        "--backoff-limit",
        "-1",
    )
    assert res.returncode != 0
    assert "must be >= 0" in res.stderr


def test_validate_download_apk_links_rejects_missing_obfuscated_metadata(
    tmp_path,
) -> None:
    app_dir = tmp_path / "apps" / "demo"
    app_dir.mkdir(parents=True)
    (app_dir / "metadata.json").write_text(
        '{"download_link": "https://github.com/owner/repo/releases/download/v1/app.apk"}'
    )

    with pytest.raises(ValueError, match="missing download_link_obfuscated"):
        generate_jobs.validate_download_apk_links(
            [{"app_name": "demo", "vuln_id": "probe-only"}],
            tmp_path,
            obfuscated_states=[True],
        )


def test_discover_probe_only_apps_includes_remote_attacker_only_apps(tmp_path) -> None:
    app_dir = tmp_path / "apps" / "demo"
    probe_dir = app_dir / "remote_attacker"
    probe_dir.mkdir(parents=True)
    for name in (
        "test_access_control.py",
        "test_availability.py",
        "test_confidentiality.py",
        "test_integrity.py",
    ):
        (probe_dir / name).write_text("# ok\n")

    experiments = generate_jobs.discover_probe_only_apps(
        tmp_path / "apps",
        None,
        ["remote_attacker"],
    )

    assert experiments == [{"app_name": "demo", "vuln_id": "probe-only"}]
