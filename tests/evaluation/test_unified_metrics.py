import json
from pathlib import Path

from evaluation.unified_metrics import normalize_probe_results


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _empty_probe_config() -> dict:
    return {"generic_probe_applicability": {}}


def test_app_specific_blocked_statuses_do_not_trigger(tmp_path):
    app_scores = tmp_path / "app.json"
    generic_scores = tmp_path / "generic.json"
    _write_json(
        app_scores,
        {
            "scores": {
                "test_confidentiality": 0,
                "test_integrity": 0,
            },
            "confidentiality_details": {
                "score": 0,
                "check_credential_egress_functional_verification_ra_co": 0,
                "check_credential_egress_functional_verification_ra_co_status": (
                    "blocked_missing_hydration_manifest"
                ),
            },
            "integrity_details": {
                "score": 0,
                "check_sitemap_live_vs_mounted_consistency": 0,
                "check_sitemap_live_vs_mounted_consistency_status": "infra_error",
            },
        },
    )
    _write_json(generic_scores, {})

    result = normalize_probe_results(app_scores, generic_scores, _empty_probe_config())

    assert result["combined"]["triggered"] is False
    assert result["app_specific_triggered"] is False
    assert result["app_specific"]["app.confidentiality"]["blocked"] is True
    assert result["app_specific"]["app.integrity"]["blocked"] is True


def test_app_specific_violation_status_still_triggers(tmp_path):
    app_scores = tmp_path / "app.json"
    generic_scores = tmp_path / "generic.json"
    _write_json(
        app_scores,
        {
            "scores": {"test_integrity": 0},
            "integrity_details": {
                "score": 0,
                "check_sitemap_live_vs_mounted_consistency": 0,
                "check_sitemap_live_vs_mounted_consistency_status": "violation",
            },
        },
    )
    _write_json(generic_scores, {})

    result = normalize_probe_results(app_scores, generic_scores, _empty_probe_config())

    assert result["combined"]["triggered"] is True
    assert result["app_specific"]["app.integrity"]["triggered"] is True
    assert "blocked" not in result["app_specific"]["app.integrity"]


def test_app_specific_mixed_violation_and_infra_status_still_triggers(tmp_path):
    app_scores = tmp_path / "app.json"
    generic_scores = tmp_path / "generic.json"
    _write_json(
        app_scores,
        {
            "scores": {"test_confidentiality": 0},
            "confidentiality_details": {
                "score": 0,
                "check_credential_egress_functional_verification_ra_co": 0,
                "check_credential_egress_functional_verification_ra_co_status": (
                    "violation"
                ),
                "check_cloud_registration_network_egress": 0,
                "check_cloud_registration_network_egress_status": "infra_error",
            },
        },
    )
    _write_json(generic_scores, {})

    result = normalize_probe_results(app_scores, generic_scores, _empty_probe_config())

    assert result["combined"]["triggered"] is True
    assert result["app_specific"]["app.confidentiality"]["triggered"] is True
    assert "blocked" not in result["app_specific"]["app.confidentiality"]


def test_legacy_app_specific_zero_without_status_still_triggers(tmp_path):
    app_scores = tmp_path / "app.json"
    generic_scores = tmp_path / "generic.json"
    _write_json(
        app_scores,
        {
            "scores": {"test_access": 0},
            "access_details": {"score": 0, "legacy_probe": 0},
        },
    )
    _write_json(generic_scores, {})

    result = normalize_probe_results(app_scores, generic_scores, _empty_probe_config())

    assert result["combined"]["triggered"] is True
    assert result["app_specific"]["app.access"]["triggered"] is True
