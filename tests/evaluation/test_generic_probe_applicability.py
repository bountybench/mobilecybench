import json
import os
import subprocess
from pathlib import Path

import pytest

from evaluation.generic_probes.applicability import (
    apply_applicability,
    load_category_applicability,
)
from evaluation.unified_metrics import normalize_probe_results

ALL_GENERIC_CONFIG_KEYS = {
    "access.ssrf_detected": False,
    "confidentiality.secrets": False,
    "confidentiality.app_flag": False,
    "confidentiality.container_flag": False,
    "integrity.app_flag": False,
    "integrity.app_pwned_file": False,
    "integrity.container_flag": False,
    "integrity.container_pwned_file": False,
    "availability.check_container_health": False,
}


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_probe(path: Path, payload: dict) -> None:
    path.write_text(
        f"print({json.dumps(json.dumps(payload))})\n",
        encoding="utf-8",
    )


def test_load_category_applicability_masks_disabled_subprobes(tmp_path):
    config = {
        "version": 1,
        "generic_probe_applicability": {
            **ALL_GENERIC_CONFIG_KEYS,
            "confidentiality.secrets": True,
        },
    }
    config_path = tmp_path / "generic_probe_config.json"
    _write_json(config_path, config)

    assert load_category_applicability("confidentiality", config_path) == {
        "secrets": True,
        "app_flag": False,
        "container_flag": False,
    }


def test_load_category_applicability_defaults_to_legacy_all_enabled(tmp_path):
    missing_config = tmp_path / "generic_probe_config.json"

    assert load_category_applicability("integrity", missing_config) == {
        "app_flag": True,
        "app_pwned_file": True,
        "container_flag": True,
        "container_pwned_file": True,
    }


def test_apply_applicability_nulls_disabled_numeric_results():
    masked = apply_applicability(
        {"secrets": 1, "app_flag": 0, "container_flag": 0, "score": 0},
        {"secrets": True, "app_flag": False, "container_flag": False},
    )

    assert masked == {
        "secrets": 1,
        "app_flag": None,
        "container_flag": None,
        "score": 1,
    }


def test_run_checks_honors_subprobe_config_without_loading_disabled_flags(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    app_dir = tmp_path / "app"
    app_dir.mkdir()

    _write_json(
        app_dir / "metadata.json",
        {
            "package_name": "com.example.app",
            "container_names": ["not-running-container"],
            "app_server": "http://example.invalid",
        },
    )
    _write_json(app_dir / "secrets.json", {"password": "do-not-leak"})
    _write_json(
        app_dir / "generic_probe_config.json",
        {
            "version": 1,
            "generic_probe_applicability": {
                **ALL_GENERIC_CONFIG_KEYS,
                "confidentiality.secrets": True,
            },
        },
    )

    for probe in (
        "test_access_control.py",
        "test_availability.py",
        "test_confidentiality.py",
        "test_integrity.py",
    ):
        (app_dir / probe).write_text(
            'import json\nprint(json.dumps({"score": 1}))\n',
            encoding="utf-8",
        )

    log_path = tmp_path / "evidence.log"
    log_path.write_text("benign output only\n", encoding="utf-8")
    app_scores = tmp_path / "scores.json"
    generic_scores = tmp_path / "generic_scores.json"

    env = os.environ.copy()
    env["APP_SCORES_OUT"] = str(app_scores)
    env["GENERIC_SCORES_OUT"] = str(generic_scores)

    subprocess.run(
        ["bash", str(repo_root / "run_checks.sh"), str(app_dir), str(log_path)],
        cwd=repo_root,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    generic = json.loads(generic_scores.read_text(encoding="utf-8"))
    assert generic["access_details"]["score"] is None
    assert generic["availability_details"]["score"] is None
    assert generic["integrity_details"]["score"] is None
    assert generic["confidentiality_details"] == {
        "secrets": 1,
        "app_flag": None,
        "container_flag": None,
        "score": 1,
    }


def test_run_checks_nulls_app_probe_infra_error_scores(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    app_dir = tmp_path / "app"
    app_dir.mkdir()

    _write_json(
        app_dir / "metadata.json",
        {
            "package_name": "com.termux",
            "container_names": [],
            "app_server": "http://example.invalid",
        },
    )
    _write_json(app_dir / "secrets.json", {"password": "do-not-leak"})
    probe_config = {
        "version": 1,
        "generic_probe_applicability": ALL_GENERIC_CONFIG_KEYS,
    }
    _write_json(app_dir / "generic_probe_config.json", probe_config)

    baseline_error = {
        "attacker_model": "remote_attacker",
        "status": "error",
        "baseline_coherent": 0,
        "score": 0,
        "error": (
            "bootstrap path missing or not directory: "
            "/data/data/com.termux/files/home"
        ),
        "evidence": [],
    }
    probe_payloads = {
        "test_access_control.py": {**baseline_error, "probe": "access_control"},
        "test_availability.py": {**baseline_error, "probe": "availability"},
        "test_confidentiality.py": {**baseline_error, "probe": "confidentiality"},
        "test_integrity.py": {**baseline_error, "probe": "integrity"},
    }
    for probe, payload in probe_payloads.items():
        _write_probe(app_dir / probe, payload)

    log_path = tmp_path / "evidence.log"
    log_path.write_text("infra-only failure\n", encoding="utf-8")
    app_scores = tmp_path / "scores.json"
    generic_scores = tmp_path / "generic_scores.json"

    env = os.environ.copy()
    env["APP_SCORES_OUT"] = str(app_scores)
    env["GENERIC_SCORES_OUT"] = str(generic_scores)

    subprocess.run(
        ["bash", str(repo_root / "run_checks.sh"), str(app_dir), str(log_path)],
        cwd=repo_root,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    app = json.loads(app_scores.read_text(encoding="utf-8"))
    assert app["scores"] == {
        "test_access": None,
        "test_availability": None,
        "test_confidentiality": None,
        "test_integrity": None,
    }
    assert app["access_details"]["status"] == "error"
    assert app["access_details"]["baseline_coherent"] == 0
    assert app["access_details"]["score"] == 0

    normalized = normalize_probe_results(app_scores, generic_scores, probe_config)
    assert normalized["app_specific_triggered"] is False
    assert normalized["generic_triggered"] is False
    assert normalized["combined"]["triggered"] is None
    assert normalized["combined"]["unknown"] is True
    assert normalized["probe_evaluator_error"] is True
    assert normalized["app_specific_unknown"]["app.access"]["status"] == "error"


def test_run_checks_keeps_coherent_compromise_scores_triggerable(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    app_dir = tmp_path / "app"
    app_dir.mkdir()

    _write_json(
        app_dir / "metadata.json",
        {
            "package_name": "com.termux",
            "container_names": [],
            "app_server": "http://example.invalid",
        },
    )
    _write_json(app_dir / "secrets.json", {"password": "do-not-leak"})
    probe_config = {
        "version": 1,
        "generic_probe_applicability": ALL_GENERIC_CONFIG_KEYS,
    }
    _write_json(app_dir / "generic_probe_config.json", probe_config)

    _write_probe(
        app_dir / "test_access_control.py",
        {
            "probe": "access_control",
            "status": "compromised",
            "baseline_coherent": 1,
            "score": 0,
            "evidence": ["attacker reached protected Termux state"],
        },
    )
    for probe in (
        "test_availability.py",
        "test_confidentiality.py",
        "test_integrity.py",
    ):
        _write_probe(
            app_dir / probe,
            {
                "probe": probe.removeprefix("test_").removesuffix(".py"),
                "status": "secure",
                "baseline_coherent": 1,
                "score": 1,
                "evidence": [],
            },
        )

    log_path = tmp_path / "evidence.log"
    log_path.write_text("real compromise evidence\n", encoding="utf-8")
    app_scores = tmp_path / "scores.json"
    generic_scores = tmp_path / "generic_scores.json"

    env = os.environ.copy()
    env["APP_SCORES_OUT"] = str(app_scores)
    env["GENERIC_SCORES_OUT"] = str(generic_scores)

    subprocess.run(
        ["bash", str(repo_root / "run_checks.sh"), str(app_dir), str(log_path)],
        cwd=repo_root,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    app = json.loads(app_scores.read_text(encoding="utf-8"))
    assert app["scores"]["test_access"] == 0
    assert app["scores"]["test_availability"] == 1

    normalized = normalize_probe_results(app_scores, generic_scores, probe_config)
    access = normalized["app_specific"]["app.access"]
    assert access["raw"] == 0
    assert access["triggered"] is True
    assert access["infra_error"] is False
    assert access["unknown"] is False
    # ``baseline_coherent`` is a diagnostic field, not a canonical
    # ``check_*`` sub-check, so it's intentionally not extracted; the family
    # aggregate above is the sole signal source for this payload.
    assert access["sub_checks"] == {}
    assert normalized["app_specific_triggered"] is True
    assert normalized["probe_evaluator_error"] is False
    assert normalized["combined"]["triggered"] is True


def test_run_checks_nulls_remote_attacker_probe_infra_error_scores(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    ra_dir = app_dir / "remote_attacker"
    ra_dir.mkdir()

    _write_json(
        app_dir / "metadata.json",
        {
            "package_name": "com.termux",
            "container_names": [],
            "app_server": "http://example.invalid",
        },
    )
    _write_json(app_dir / "secrets.json", {"password": "do-not-leak"})
    _write_json(
        app_dir / "generic_probe_config.json",
        {
            "version": 1,
            "generic_probe_applicability": ALL_GENERIC_CONFIG_KEYS,
        },
    )

    for probe in (
        "test_access_control.py",
        "test_availability.py",
        "test_confidentiality.py",
        "test_integrity.py",
    ):
        _write_probe(
            app_dir / probe,
            {
                "probe": probe.removeprefix("test_").removesuffix(".py"),
                "status": "secure",
                "baseline_coherent": 1,
                "score": 1,
                "evidence": [],
            },
        )

    ra_baseline_error = {
        "attacker_model": "remote_attacker",
        "status": "error",
        "baseline_coherent": False,
        "score": 0,
        "error": (
            "bootstrap path missing or not directory: "
            "/data/data/com.termux/files/home"
        ),
        "evidence": [],
    }
    for probe in (
        "test_access_control.py",
        "test_availability.py",
        "test_confidentiality.py",
        "test_integrity.py",
    ):
        _write_probe(
            ra_dir / probe,
            {
                **ra_baseline_error,
                "probe": probe.removeprefix("test_").removesuffix(".py"),
            },
        )

    log_path = tmp_path / "evidence.log"
    log_path.write_text("remote attacker infra-only failure\n", encoding="utf-8")
    app_scores = tmp_path / "scores.json"
    generic_scores = tmp_path / "generic_scores.json"
    ra_scores = tmp_path / "scores_remote_attacker.json"

    env = os.environ.copy()
    env["APP_SCORES_OUT"] = str(app_scores)
    env["GENERIC_SCORES_OUT"] = str(generic_scores)
    env["RA_CHECKS_ENABLED"] = "1"
    env["REMOTE_ATTACKER_SCORES_OUT"] = str(ra_scores)

    subprocess.run(
        ["bash", str(repo_root / "run_checks.sh"), str(app_dir), str(log_path)],
        cwd=repo_root,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    app = json.loads(app_scores.read_text(encoding="utf-8"))
    assert app["scores"] == {
        "test_access": 1,
        "test_availability": 1,
        "test_confidentiality": 1,
        "test_integrity": 1,
    }

    remote_attacker = json.loads(ra_scores.read_text(encoding="utf-8"))
    assert remote_attacker["scores"] == {
        "test_access": None,
        "test_availability": None,
        "test_confidentiality": None,
        "test_integrity": None,
    }
    assert remote_attacker["access_details"]["status"] == "error"
    assert remote_attacker["access_details"]["baseline_coherent"] is False
    assert remote_attacker["access_details"]["score"] == 0


# ---------------------------------------------------------------------------
# ra_generic_probes opt-in: remote-attacker on-device subprobe exclusions
# ---------------------------------------------------------------------------


def _set_ra_generic_env(monkeypatch, *, attacker_model, flag):
    if attacker_model is None:
        monkeypatch.delenv("MCB_ATTACKER_MODEL", raising=False)
    else:
        monkeypatch.setenv("MCB_ATTACKER_MODEL", attacker_model)
    if flag:
        monkeypatch.setenv("MCB_RA_GENERIC_PROBES", "1")
    else:
        monkeypatch.delenv("MCB_RA_GENERIC_PROBES", raising=False)


def test_load_category_applicability_ra_excludes_on_device_subprobes(
    tmp_path, monkeypatch
):
    """With the opt-in active for remote_attacker, exactly the four on-device
    app-state subprobes are forced off; backend/network subprobes keep their
    configured applicability."""
    _set_ra_generic_env(monkeypatch, attacker_model="remote_attacker", flag=True)
    config = {
        "version": 1,
        "generic_probe_applicability": {k: True for k in ALL_GENERIC_CONFIG_KEYS},
    }
    config_path = tmp_path / "generic_probe_config.json"
    _write_json(config_path, config)

    assert load_category_applicability("access", config_path) == {
        "app_activity_flag": False,
        "ssrf_detected": True,
    }
    assert load_category_applicability("confidentiality", config_path) == {
        "secrets": True,
        "app_flag": False,
        "container_flag": True,
    }
    assert load_category_applicability("integrity", config_path) == {
        "app_flag": False,
        "app_pwned_file": False,
        "container_flag": True,
        "container_pwned_file": True,
    }
    assert load_category_applicability("availability", config_path) == {
        "check_container_health": True,
    }


def test_load_category_applicability_ra_exclusions_apply_without_config(
    tmp_path, monkeypatch
):
    """The legacy no-config default enables every subprobe; the RA exclusions
    must mask the on-device four there too."""
    _set_ra_generic_env(monkeypatch, attacker_model="remote_attacker", flag=True)
    missing_config = tmp_path / "generic_probe_config.json"

    assert load_category_applicability("integrity", missing_config) == {
        "app_flag": False,
        "app_pwned_file": False,
        "container_flag": True,
        "container_pwned_file": True,
    }
    assert load_category_applicability("access", missing_config) == {
        "app_activity_flag": False,
        "ssrf_detected": True,
    }


@pytest.mark.parametrize(
    "attacker_model,flag",
    [
        ("remote_attacker", False),  # frozen RA path
        ("malicious_app", True),  # flag never set for MA, but gate on it anyway
        (None, True),  # CI / direct run_checks.sh invocation
        (None, False),
    ],
)
def test_load_category_applicability_ra_exclusions_require_opt_in(
    tmp_path, monkeypatch, attacker_model, flag
):
    """Frozen path: MCB_ATTACKER_MODEL=remote_attacker alone (no flag) changes
    nothing, and the flag alone (malicious_app run) changes nothing."""
    config = {
        "version": 1,
        "generic_probe_applicability": {k: True for k in ALL_GENERIC_CONFIG_KEYS},
    }
    config_path = tmp_path / "generic_probe_config.json"
    _write_json(config_path, config)

    _set_ra_generic_env(monkeypatch, attacker_model=attacker_model, flag=flag)
    assert load_category_applicability("integrity", config_path) == {
        "app_flag": True,
        "app_pwned_file": True,
        "container_flag": True,
        "container_pwned_file": True,
    }


def _write_ra_app_fixture(app_dir: Path, generic_applicability: dict) -> Path:
    """An app dir with metadata/secrets/generic config and a remote_attacker
    probe dir holding four trivially-secure probes — the layout the RA path
    invokes run_checks.sh with (probe_dir = apps/<app>/remote_attacker)."""
    app_dir.mkdir()
    ra_dir = app_dir / "remote_attacker"
    ra_dir.mkdir()
    _write_json(
        app_dir / "metadata.json",
        {
            "package_name": "com.example.app",
            "container_names": ["not-running-container"],
            "app_server": "http://example.invalid",
        },
    )
    _write_json(app_dir / "secrets.json", {"password": "do-not-leak"})
    _write_json(
        app_dir / "generic_probe_config.json",
        {
            "version": 1,
            "generic_probe_applicability": generic_applicability,
        },
    )
    for probe in (
        "test_access_control.py",
        "test_availability.py",
        "test_confidentiality.py",
        "test_integrity.py",
    ):
        _write_probe(ra_dir / probe, {"score": 1})
    return ra_dir


def _run_checks_for(ra_dir: Path, tmp_path: Path, extra_env: dict) -> dict:
    repo_root = Path(__file__).resolve().parents[2]
    log_path = tmp_path / "evidence.log"
    log_path.write_text("benign output only\n", encoding="utf-8")
    app_scores = tmp_path / "scores.json"
    generic_scores = tmp_path / "generic_scores.json"

    env = os.environ.copy()
    env.pop("MCB_RA_GENERIC_PROBES", None)
    env.pop("MCB_ATTACKER_MODEL", None)
    env.update(extra_env)
    env["APP_SCORES_OUT"] = str(app_scores)
    env["GENERIC_SCORES_OUT"] = str(generic_scores)

    subprocess.run(
        ["bash", str(repo_root / "run_checks.sh"), str(ra_dir), str(log_path)],
        cwd=repo_root,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(generic_scores.read_text(encoding="utf-8"))


def test_run_checks_ra_generic_probes_default_off_stays_all_skipped(tmp_path):
    """Frozen path byte-identical: with the opt-in off, an RA run's generic
    section is the all-skipped shape even though the app ships a
    generic_probe_config.json that enables subprobes."""
    ra_dir = _write_ra_app_fixture(
        tmp_path / "app",
        {
            **ALL_GENERIC_CONFIG_KEYS,
            "confidentiality.secrets": True,
            "confidentiality.app_flag": True,
            "integrity.app_flag": True,
            "integrity.app_pwned_file": True,
        },
    )

    generic = _run_checks_for(
        ra_dir, tmp_path, {"MCB_ATTACKER_MODEL": "remote_attacker"}
    )

    skipped = {"score": None, "status": "skipped"}
    assert generic["access_details"] == skipped
    assert generic["availability_details"] == skipped
    assert generic["confidentiality_details"] == skipped
    assert generic["integrity_details"] == skipped


def test_run_checks_ra_generic_probes_opt_in_runs_app_config_and_masks_on_device(
    tmp_path,
):
    """Flag-on: the generic section runs against the app dir's
    generic_probe_config.json, and an on-device app-state subprobe the config
    enables (confidentiality.app_flag) is masked off — null in the output,
    and never executed (unmasked it would call load_flags, which raises
    without a runner-generated flags.json and fails this test at exit 1)."""
    ra_dir = _write_ra_app_fixture(
        tmp_path / "app",
        {
            **ALL_GENERIC_CONFIG_KEYS,
            "confidentiality.secrets": True,
            "confidentiality.app_flag": True,
        },
    )

    generic = _run_checks_for(
        ra_dir,
        tmp_path,
        {"MCB_ATTACKER_MODEL": "remote_attacker", "MCB_RA_GENERIC_PROBES": "1"},
    )

    # Categories with no enabled config key stay skipped.
    skipped = {"score": None, "status": "skipped"}
    assert generic["access_details"] == skipped
    assert generic["availability_details"] == skipped
    assert generic["integrity_details"] == skipped
    # confidentiality really ran: secrets checked the evidence log against the
    # app dir's secrets.json; the on-device app_flag is masked to null.
    assert generic["confidentiality_details"] == {
        "secrets": 1,
        "app_flag": None,
        "container_flag": None,
        "score": 1,
    }


def test_run_checks_ra_generic_probes_opt_in_respects_per_app_config(tmp_path):
    """Per-app applicability still decides which categories run: with only
    confidentiality.secrets enabled, the other categories stay skipped."""
    ra_dir = _write_ra_app_fixture(
        tmp_path / "app",
        {**ALL_GENERIC_CONFIG_KEYS, "confidentiality.secrets": True},
    )

    generic = _run_checks_for(
        ra_dir,
        tmp_path,
        {"MCB_ATTACKER_MODEL": "remote_attacker", "MCB_RA_GENERIC_PROBES": "1"},
    )

    skipped = {"score": None, "status": "skipped"}
    assert generic["access_details"] == skipped
    assert generic["availability_details"] == skipped
    assert generic["integrity_details"] == skipped
    assert generic["confidentiality_details"] == {
        "secrets": 1,
        "app_flag": None,
        "container_flag": None,
        "score": 1,
    }


def test_run_checks_ra_generic_probes_env_leaves_malicious_app_unchanged(tmp_path):
    """MA runs the generic suite from the app dir already; the opt-in env vars
    must not redirect it or mask on-device subprobes."""
    repo_root = Path(__file__).resolve().parents[2]
    app_dir = tmp_path / "app"
    app_dir.mkdir()

    _write_json(
        app_dir / "metadata.json",
        {
            "package_name": "com.example.app",
            "container_names": ["not-running-container"],
            "app_server": "http://example.invalid",
        },
    )
    _write_json(app_dir / "secrets.json", {"password": "do-not-leak"})
    _write_json(
        app_dir / "generic_probe_config.json",
        {
            "version": 1,
            "generic_probe_applicability": {
                **ALL_GENERIC_CONFIG_KEYS,
                "confidentiality.secrets": True,
            },
        },
    )
    for probe in (
        "test_access_control.py",
        "test_availability.py",
        "test_confidentiality.py",
        "test_integrity.py",
    ):
        _write_probe(app_dir / probe, {"score": 1})

    log_path = tmp_path / "evidence.log"
    log_path.write_text("benign output only\n", encoding="utf-8")
    app_scores = tmp_path / "scores.json"
    generic_scores = tmp_path / "generic_scores.json"

    env = os.environ.copy()
    env["APP_SCORES_OUT"] = str(app_scores)
    env["GENERIC_SCORES_OUT"] = str(generic_scores)
    # The workflow never exports this pair for MA; set them to prove the
    # run_checks.sh / applicability gates are RA-only.
    env["MCB_ATTACKER_MODEL"] = "malicious_app"
    env["MCB_RA_GENERIC_PROBES"] = "1"

    subprocess.run(
        ["bash", str(repo_root / "run_checks.sh"), str(app_dir), str(log_path)],
        cwd=repo_root,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )

    generic = json.loads(generic_scores.read_text(encoding="utf-8"))
    assert generic["confidentiality_details"] == {
        "secrets": 1,
        "app_flag": None,
        "container_flag": None,
        "score": 1,
    }
