import json
import os
import subprocess
from pathlib import Path

from evaluation.generic_probes.applicability import (
    apply_applicability,
    load_category_applicability,
)

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
