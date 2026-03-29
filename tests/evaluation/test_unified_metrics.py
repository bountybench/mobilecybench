"""Tests for unified workflow probe result normalization."""

import json

from evaluation.unified_metrics import normalize_probe_results


def _make_hidden_config(**probe_overrides):
    """Build a hidden eval config with all probes disabled by default."""
    probes = {
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
    probes.update(probe_overrides)
    return {"version": 1, "generic_probe_applicability": probes}


def _write_scores(tmp_path, filename, scores_dict):
    path = tmp_path / filename
    path.write_text(json.dumps(scores_dict), encoding="utf-8")
    return path


class TestNormalization:
    def test_all_secure_no_trigger(self, tmp_path):
        """All scores=1 means no probes triggered."""
        app_path = _write_scores(
            tmp_path,
            "app.json",
            {
                "scores": {
                    "test_access": 1,
                    "test_availability": 1,
                    "test_confidentiality": 1,
                    "test_integrity": 1,
                }
            },
        )
        generic_path = _write_scores(
            tmp_path,
            "generic.json",
            {
                "scores": {
                    "test_access": 1,
                    "test_availability": 1,
                    "test_confidentiality": 1,
                    "test_integrity": 1,
                },
                "access_details": {"ssrf_detected": 1},
                "confidentiality_details": {
                    "secrets": 1,
                    "app_flag": 1,
                    "container_flag": 1,
                },
                "integrity_details": {
                    "app_flag": 1,
                    "app_pwned_file": 1,
                    "container_flag": 1,
                    "container_pwned_file": 1,
                },
                "availability_details": {"check_container_health": 1},
            },
        )

        config = _make_hidden_config(
            **{
                "access.ssrf_detected": True,
                "confidentiality.secrets": True,
            }
        )
        result = normalize_probe_results(app_path, generic_path, config)

        assert result["combined"]["triggered"] is False
        assert result["app_specific_triggered"] is False
        assert result["generic_triggered"] is False

    def test_one_enabled_generic_failure_triggers(self, tmp_path):
        """One enabled generic probe with value 0 = triggered."""
        app_path = _write_scores(
            tmp_path,
            "app.json",
            {
                "scores": {
                    "test_access": 1,
                    "test_availability": 1,
                    "test_confidentiality": 1,
                    "test_integrity": 1,
                }
            },
        )
        generic_path = _write_scores(
            tmp_path,
            "generic.json",
            {
                "confidentiality_details": {"secrets": 0},  # compromised!
            },
        )

        config = _make_hidden_config(**{"confidentiality.secrets": True})
        result = normalize_probe_results(app_path, generic_path, config)

        assert result["combined"]["triggered"] is True
        assert result["generic_triggered"] is True
        assert result["app_specific_triggered"] is False

    def test_disabled_probe_with_value_zero_not_triggered(self, tmp_path):
        """A probe that's disabled in config should not count even if raw=0."""
        app_path = _write_scores(
            tmp_path,
            "app.json",
            {
                "scores": {
                    "test_access": 1,
                    "test_availability": 1,
                    "test_confidentiality": 1,
                    "test_integrity": 1,
                }
            },
        )
        generic_path = _write_scores(
            tmp_path,
            "generic.json",
            {
                "confidentiality_details": {"secrets": 0},  # compromised but disabled
            },
        )

        config = _make_hidden_config(**{"confidentiality.secrets": False})
        result = normalize_probe_results(app_path, generic_path, config)

        assert result["combined"]["triggered"] is False
        assert result["generic_triggered"] is False

    def test_app_specific_failure_triggers(self, tmp_path):
        """App-specific probe with value 0 = triggered."""
        app_path = _write_scores(
            tmp_path,
            "app.json",
            {
                "scores": {
                    "test_access": 0,  # compromised
                    "test_availability": 1,
                    "test_confidentiality": 1,
                    "test_integrity": 1,
                }
            },
        )
        generic_path = _write_scores(tmp_path, "generic.json", {})

        config = _make_hidden_config()
        result = normalize_probe_results(app_path, generic_path, config)

        assert result["combined"]["triggered"] is True
        assert result["app_specific_triggered"] is True

    def test_missing_files_return_no_trigger(self, tmp_path):
        """Missing score files should not crash or trigger."""
        config = _make_hidden_config(**{"confidentiality.secrets": True})
        result = normalize_probe_results(
            tmp_path / "nonexistent_app.json",
            tmp_path / "nonexistent_generic.json",
            config,
        )
        assert result["combined"]["triggered"] is False
