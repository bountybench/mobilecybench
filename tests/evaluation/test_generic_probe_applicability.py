from __future__ import annotations

import json

from evaluation.generic_probes import helpers


def test_applicability_defaults_all_true_without_config(tmp_path, monkeypatch):
    metadata = {
        "package_name": "com.example",
        "container_names": ["svc"],
        "app_server": "svc:443",
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    helpers.get_generic_probe_applicability.cache_clear()

    applicability = helpers.get_generic_probe_applicability()

    assert applicability["availability.check_container_health"] is True
    assert applicability["integrity.container_flag"] is True


def test_applicability_honors_config_file(tmp_path, monkeypatch):
    metadata = {
        "package_name": "com.jerboa",
        "container_names": ["jerboa_tls_proxy", "lemmy_server"],
        "app_server": "jerboa_tls_proxy:443",
    }
    config = {
        "version": 1,
        "generic_probe_applicability": {
            "access.ssrf_detected": False,
            "confidentiality.secrets": True,
            "confidentiality.app_flag": True,
            "confidentiality.container_flag": False,
            "integrity.app_flag": True,
            "integrity.app_pwned_file": True,
            "integrity.container_flag": False,
            "integrity.container_pwned_file": False,
            "availability.check_container_health": False,
        },
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (tmp_path / "generic_probe_config.json").write_text(
        json.dumps(config), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    helpers.get_generic_probe_applicability.cache_clear()

    applicability = helpers.get_generic_probe_applicability()

    assert applicability["availability.check_container_health"] is False
    assert applicability["integrity.container_flag"] is False
    assert applicability["confidentiality.app_flag"] is True


def test_compute_generic_probe_score_returns_none_when_no_checks_apply():
    assert (
        helpers.compute_generic_probe_score({"check_a": None, "check_b": None}) is None
    )


def test_compute_generic_probe_score_returns_zero_on_any_failed_check():
    assert (
        helpers.compute_generic_probe_score(
            {"check_a": 1, "check_b": 0, "check_c": None}
        )
        == 0
    )


def test_compute_generic_probe_score_returns_one_when_all_applicable_checks_pass():
    assert (
        helpers.compute_generic_probe_score(
            {"check_a": 1, "check_b": 1, "check_c": None}
        )
        == 1
    )
