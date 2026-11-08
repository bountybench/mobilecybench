"""source_with_apk: the APK-only setting plus the source mount (matched source-access ablation)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import difflib
import json

import docker.errors
import pytest

from agent.prompts.prompts import build_malicious_app_prompt, build_remote_attacker_prompt
from agent.runtime.container import AgentEnvironment
from models.config import RunnerConfig

REPO_ROOT = Path(__file__).resolve().parents[1]


def _config(**overrides) -> RunnerConfig:
    """A cell of the APK-plus-source batch config, with overrides."""
    payload = json.loads((REPO_ROOT / "runner_config_batch_apk_plus_source.json").read_text())
    payload.pop("batch")
    payload.pop("$schema", None)
    payload["attacker_model"] = "malicious_app"
    payload.update(overrides)
    return RunnerConfig.model_validate(payload)


def test_source_with_apk_requires_no_codebase():
    with pytest.raises(ValueError, match="source_with_apk"):
        _config(no_codebase=False, apk_obfuscation="off")


def test_source_with_apk_allows_obfuscated_apk_and_restricted_network():
    c = _config()
    assert c.source_with_apk and c.no_codebase
    assert c.apk_obfuscation == "on" and c.network_mode == "restricted"


def test_source_with_apk_defaults_off():
    assert RunnerConfig.model_fields["source_with_apk"].default is False


@pytest.mark.parametrize("builder", [build_malicious_app_prompt, build_remote_attacker_prompt])
def test_prompt_is_apk_only_prompt_plus_codebase_bullet(builder):
    kw = dict(package_name="com.example", app_server="srv:80", username="u", password="p",
              agent_mode="external")
    apk = builder(**kw, no_codebase=True)
    both = builder(**kw, no_codebase=True, source_with_apk=True)
    apk_bullet = "**APK** — the application APK at `/app/apk/`"
    code_bullet = "- **Codebase** — full application source with git history at `/app/codebase`"
    assert apk_bullet in both and code_bullet in both
    assert code_bullet not in apk
    # Exactly three line changes: the added codebase bullet, and the two
    # "analyze the APK" lines now naming both resources.
    changed = [l for l in difflib.unified_diff(apk.splitlines(), both.splitlines(), lineterm="", n=0)
               if l[:1] in "+-" and l[:3] not in ("+++", "---")]
    added = [l[1:] for l in changed if l.startswith("+")]
    removed = [l[1:] for l in changed if l.startswith("-")]
    assert code_bullet in added
    assert len(added) == len(removed) + 1
    for old, new in zip(removed, [l for l in added if l != code_bullet]):
        assert new == old.replace("the APK", "the APK and codebase", 1) or new == old.replace(
            "the **APK**", "the **APK and codebase**", 1)


@patch("agent.runtime.container.docker.from_env")
def test_agent_container_mounts_apk_and_codebase(mock_from_env, tmp_path):
    client = MagicMock()
    mock_from_env.return_value = client
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=0, output=b"")
    client.containers.run.return_value = container
    client.containers.get.side_effect = docker.errors.NotFound("not found")
    app_dir = tmp_path / "app"
    (app_dir / "codebase").mkdir(parents=True)
    apk = tmp_path / "x.apk"
    apk.write_bytes(b"apk")

    env = AgentEnvironment(
        app_dir=app_dir, docker_networks=["n"], image_name="i:1", env={},
        commit_id="HEAD", no_codebase=True, apk_path=apk, source_with_apk=True,
    )
    with patch.object(
        env, "_setup_agent_codebase",
        return_value={str(app_dir / "agent_codebase"): {"bind": "/app/codebase", "mode": "ro"}},
    ):
        env.setup()
    binds = {v["bind"] for v in client.containers.run.call_args.kwargs["volumes"].values()}
    assert {"/app/apk", "/app/codebase"} <= binds


@patch("agent.runtime.container.docker.from_env")
def test_agent_container_apk_only_has_no_codebase(mock_from_env, tmp_path):
    client = MagicMock()
    mock_from_env.return_value = client
    container = MagicMock()
    container.exec_run.return_value = MagicMock(exit_code=0, output=b"")
    client.containers.run.return_value = container
    client.containers.get.side_effect = docker.errors.NotFound("not found")
    apk = tmp_path / "x.apk"
    apk.write_bytes(b"apk")
    env = AgentEnvironment(
        app_dir=tmp_path / "app", docker_networks=["n"], image_name="i:1", env={},
        no_codebase=True, apk_path=apk,
    )
    with patch.object(env, "_setup_agent_codebase") as cb:
        env.setup()
    cb.assert_not_called()
    binds = {v["bind"] for v in client.containers.run.call_args.kwargs["volumes"].values()}
    assert "/app/codebase" not in binds
