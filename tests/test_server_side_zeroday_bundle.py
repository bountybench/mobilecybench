"""Unit tests for server-side zero-day support (image-swap strategy).

Covers the pure-Python surface:
  - evaluation.task_bundle.ZerodayBundle server-side branching
  - evaluation.backend_image_swap override generation

The docker/e2e path (actually swapping the backend image mid-run) is validated
separately on a Docker host — see documentation/server_side_zeroday_image_swap.md.
"""

import json
from pathlib import Path

import pytest

from evaluation import backend_image_swap
from evaluation.task_bundle import ZerodayBundle

SERVER_SIDE = {
    "service": "wallabag",
    "images": {
        "vulnerable": "mcb-zeroday-wallabag:report-2-vulnerable",
        "secure": "mcb-zeroday-wallabag:report-2-patched",
    },
    "build": {
        "base_image": "wallabag/wallabag:2.6.10",
        "patch_workdir": "/var/www/wallabag",
        "patch_strip": 1,
    },
}


def _make_bundle(tmp_path: Path, server_side=None) -> ZerodayBundle:
    task_dir = tmp_path / "zerodays" / "reports" / "wallabag" / "report-2" / "task"
    task_dir.mkdir(parents=True)
    meta = {
        "schema_version": 1,
        "task_id": "wallabag-annotation-idor",
        "title": "IDOR",
        "attacker_model": "remote_attacker",
        "baseline": {"commit": "abc123"},
    }
    if server_side is not None:
        meta["server_side"] = server_side
    (task_dir / "metadata.json").write_text(json.dumps(meta))
    (task_dir / "fix.patch").write_text("diff --git a/x b/x\n")
    return ZerodayBundle(project_root=tmp_path, app_name="wallabag", task="report-2")


# --- server_side metadata parsing ---------------------------------------


def test_absent_server_side_is_app_side(tmp_path):
    b = _make_bundle(tmp_path)
    assert b.server_side() is None
    assert b.is_server_side() is False


def test_present_server_side(tmp_path):
    b = _make_bundle(tmp_path, SERVER_SIDE)
    assert b.is_server_side() is True
    assert b.backend_service() == "wallabag"


def test_malformed_server_side_raises(tmp_path):
    b = _make_bundle(tmp_path, {"service": "wallabag"})  # no images
    with pytest.raises(ValueError):
        b.server_side()


def test_backend_image_for_phase(tmp_path):
    b = _make_bundle(tmp_path, SERVER_SIDE)
    assert b.backend_image_for_phase("vulnerable").endswith("report-2-vulnerable")
    assert b.backend_image_for_phase("secure").endswith("report-2-patched")
    with pytest.raises(ValueError):
        b.backend_image_for_phase("bogus")


# --- phase-2 behavior branches ------------------------------------------


def test_phase2_codebase_server_side_skips_git_apply(tmp_path, monkeypatch):
    b = _make_bundle(tmp_path, SERVER_SIDE)
    restored, applied = [], []
    monkeypatch.setattr(
        "evaluation.task_bundle.git_restore_clean", lambda d: restored.append(d)
    )
    monkeypatch.setattr(
        "evaluation.task_bundle._git_apply", lambda d, p: applied.append((d, p))
    )
    b.prepare_phase2_codebase(tmp_path / "codebase")
    assert restored, "codebase should still be restored to clean"
    assert not applied, "server-side must NOT git-apply into the app codebase"


def test_phase2_codebase_app_side_applies_patch(tmp_path, monkeypatch):
    b = _make_bundle(tmp_path)  # app-side
    applied = []
    monkeypatch.setattr("evaluation.task_bundle.git_restore_clean", lambda d: None)
    monkeypatch.setattr(
        "evaluation.task_bundle._git_apply", lambda d, p: applied.append((d, p))
    )
    b.prepare_phase2_codebase(tmp_path / "codebase")
    assert len(applied) == 1, "app-side must apply fix.patch to the codebase"


def test_build_apks_server_side_skips_hardened(tmp_path, monkeypatch):
    b = _make_bundle(tmp_path, SERVER_SIDE)
    calls = []
    monkeypatch.setattr(
        "evaluation.task_bundle._run_build",
        lambda root, args, timeout: calls.append(args),
    )
    b.build_apks("wallabag", tmp_path, timeout=1)
    assert len(calls) == 1, "server-side builds only the baseline APK"
    assert "--hardened-patch" not in " ".join(calls[0])


def test_build_apks_app_side_builds_hardened(tmp_path, monkeypatch):
    b = _make_bundle(tmp_path)
    calls = []
    monkeypatch.setattr(
        "evaluation.task_bundle._run_build",
        lambda root, args, timeout: calls.append(args),
    )
    b.build_apks("wallabag", tmp_path, timeout=1)
    assert len(calls) == 2
    assert any("--hardened-patch" in " ".join(a) for a in calls)


def test_validate_server_side_skips_hardened_apk(tmp_path, monkeypatch):
    b = _make_bundle(tmp_path, SERVER_SIDE)
    apk = tmp_path / "baseline.apk"
    apk.write_text("x")
    monkeypatch.setattr(ZerodayBundle, "phase1_apk", lambda self: apk)
    # Must not raise despite no hardened APK on disk.
    b.validate_build_artifacts(tmp_path / "apps" / "wallabag")


# --- override generation ------------------------------------------------


def test_image_key_for_phase():
    assert backend_image_swap.image_key_for_phase("vulnerable") == "vulnerable"
    assert backend_image_swap.image_key_for_phase("secure") == "secure"
    assert backend_image_swap.image_key_for_phase("nope") is None


def test_write_override_and_env(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    env = backend_image_swap.write_phase_override(
        tmp_path, "wallabag", "img:patched", "secure"
    )
    assert env == {
        "COMPOSE_FILE": f"docker-compose.yml:{backend_image_swap.OVERRIDE_FILENAME}"
    }
    ov = (tmp_path / backend_image_swap.OVERRIDE_FILENAME).read_text()
    assert "wallabag:" in ov
    assert "image: img:patched" in ov
    assert "build: !reset null" in ov


def test_write_override_yaml_base(tmp_path):
    (tmp_path / "docker-compose.yaml").write_text("services: {}\n")
    env = backend_image_swap.write_phase_override(
        tmp_path, "home-assistant-server", "img:v", "vulnerable"
    )
    assert env["COMPOSE_FILE"].startswith("docker-compose.yaml:")


def test_write_override_no_base_returns_empty(tmp_path):
    env = backend_image_swap.write_phase_override(tmp_path, "svc", "img", "secure")
    assert env == {}
    assert not (tmp_path / backend_image_swap.OVERRIDE_FILENAME).exists()


def test_clear_override_idempotent(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    backend_image_swap.write_phase_override(tmp_path, "svc", "img", "secure")
    backend_image_swap.clear_phase_override(tmp_path)
    backend_image_swap.clear_phase_override(tmp_path)  # no raise
    assert not (tmp_path / backend_image_swap.OVERRIDE_FILENAME).exists()
