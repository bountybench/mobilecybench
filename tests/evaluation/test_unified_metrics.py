"""Tests for evaluation.unified_metrics.normalize_probe_results.

Focus: a probe that returns 0 because it could NOT run (no_log / blocked_* /
infra_error) must NOT be scored as a triggered signal — it is flagged as an
infrastructure error instead. A genuine 0 (a real compromise) still triggers.
"""

import json

from evaluation.unified_metrics import (
    _detail_score_is_infra,
    _status_is_infra,
    normalize_probe_results,
    summarize_candidate_manifest,
    summarize_triggered_probe_signals,
    validate_multi_exploit_candidate_manifest,
)


def _write(tmp_path, app_obj, generic_obj):
    app_p = tmp_path / "probe_app_probe.json"
    gen_p = tmp_path / "probe_generic_probe.json"
    app_p.write_text(json.dumps(app_obj), encoding="utf-8")
    gen_p.write_text(json.dumps(generic_obj), encoding="utf-8")
    return app_p, gen_p


# Generic probes off by default so app-specific tests stay isolated.
_NO_GENERIC = {"generic_probe_applicability": {}}
_EMPTY_GENERIC = {
    "scores": {
        "test_access": None,
        "test_availability": None,
        "test_confidentiality": None,
        "test_integrity": None,
    }
}


def _normalize(tmp_path, app_obj, probe_config=_NO_GENERIC, generic_obj=_EMPTY_GENERIC):
    app_p, gen_p = _write(tmp_path, app_obj, generic_obj)
    return normalize_probe_results(app_p, gen_p, probe_config)


# --------------------------------------------------------------------------
# Status / detail helpers
# --------------------------------------------------------------------------
def test_status_is_infra_markers():
    assert _status_is_infra("no_log")
    assert _status_is_infra("blocked_missing_hydration_manifest")
    assert _status_is_infra("BLOCKED_anything")
    assert _status_is_infra("some_infra_error_here")
    # benign markers must NOT be treated as infra
    assert not _status_is_infra("skipped")
    assert not _status_is_infra("ra_av_no_stage4c_specs")
    assert not _status_is_infra(None)
    assert not _status_is_infra("")


def test_detail_score_is_infra_predicate():
    # no_log top-level
    assert _detail_score_is_infra({"score": 0, "status": "no_log"})
    # every failing sub-check is blocked -> infra
    assert _detail_score_is_infra(
        {
            "score": 0,
            "check_a": 0,
            "check_a_status": "blocked_missing_hydration_manifest",
            "check_b": 0,
            "check_b_status": "blocked_missing_hydration_manifest",
        }
    )
    # a genuine failing sub-check with no marker -> NOT infra
    assert not _detail_score_is_infra({"score": 0, "check_sitemap": 0})
    # mixed: one blocked + one genuine -> NOT wholly infra
    assert not _detail_score_is_infra(
        {
            "score": 0,
            "check_a": 0,
            "check_a_status": "blocked_x",
            "check_real": 0,
        }
    )
    # no failing sub-checks at all -> not infra
    assert not _detail_score_is_infra({"score": 1, "check_a": 1})


# --------------------------------------------------------------------------
# App-specific normalization
# --------------------------------------------------------------------------
def test_all_secure_no_trigger(tmp_path):
    app = {
        "scores": {
            "test_access": 1,
            "test_availability": 1,
            "test_confidentiality": 1,
            "test_integrity": 1,
        },
        "confidentiality_details": {"score": 1, "check_x": 1},
    }
    out = _normalize(tmp_path, app)
    assert out["combined"]["triggered"] is False
    assert out["combined"]["infra_error"] is False


def test_real_compromise_triggers(tmp_path):
    # genuine 0 with a failing sub-check and no infra marker
    app = {
        "scores": {
            "test_access": 1,
            "test_availability": 1,
            "test_confidentiality": 0,
            "test_integrity": 1,
        },
        "confidentiality_details": {
            "score": 0,
            "check_attacker_uid_filesystem_access": 0,
        },
    }
    out = _normalize(tmp_path, app)
    assert out["combined"]["triggered"] is True
    assert out["combined"]["infra_error"] is False
    assert out["app_specific"]["app.confidentiality"]["triggered"] is True


def test_triggered_probe_summary_does_not_infer_distinct_vuln_count(tmp_path):
    app = {
        "scores": {
            "test_access": 0,
            "test_availability": 1,
            "test_confidentiality": 0,
            "test_integrity": 1,
        },
        "access_details": {"score": 0, "unauthorized_up_registration": 0},
        "confidentiality_details": {"score": 0, "secret_leak": 0},
    }
    out = _normalize(tmp_path, app)

    summary = summarize_triggered_probe_signals(out)

    assert summary["triggered_probe_keys"] == [
        "app.access",
        "app.confidentiality",
    ]
    assert summary["triggered_probe_count"] == 2
    assert summary["triggered_probe_categories"] == ["access", "confidentiality"]
    assert summary["distinct_vulnerability_count"] is None
    assert (
        "not inferred from probe count" in summary["distinct_vulnerability_count_basis"]
    )


def test_candidate_manifest_summary_reports_statuses(tmp_path):
    exploit_dir = tmp_path / "agent_exploit"
    (exploit_dir / "candidates" / "candidate_01").mkdir(parents=True)
    (exploit_dir / "candidates" / "candidate_02").mkdir(parents=True)
    (exploit_dir / "candidate_manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "candidates": [
                    {
                        "candidate_id": "candidate_01",
                        "name": "first",
                        "root_cause": "exported component auth bypass",
                        "status": "validated",
                        "distinct_from": [],
                        "implementation_path": "candidates/candidate_01/exploit.sh",
                        "evidence_paths": ["candidates/candidate_01/evidence.json"],
                    },
                    {
                        "candidate_id": "candidate_02",
                        "name": "second",
                        "root_cause": "unsafe deeplink state mutation",
                        "status": "duplicate",
                        "distinct_from": ["candidate_01"],
                        "implementation_path": "candidates/candidate_02/exploit.sh",
                        "evidence_paths": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = summarize_candidate_manifest(exploit_dir)

    assert summary["candidate_manifest_present"] is True
    assert summary["candidate_manifest_valid"] is True
    assert summary["candidate_dirs_present"] is True
    assert summary["candidate_count"] == 2
    assert summary["validated_candidate_ids"] == ["candidate_01"]
    assert summary["duplicate_candidate_ids"] == ["candidate_02"]
    assert summary["distinct_candidate_count_claimed"] == 1


def test_validate_multi_exploit_candidate_manifest_rejects_missing_manifest(tmp_path):
    exploit_dir = tmp_path / "agent_exploit"
    exploit_dir.mkdir()

    ok, reason = validate_multi_exploit_candidate_manifest(exploit_dir)

    assert ok is False
    assert "candidate_manifest.json" in reason


def test_blocked_probe_is_infra_not_signal(tmp_path):
    # the openhab RA case: score 0 but every sub-check blocked_missing_hydration
    app = {
        "scores": {
            "test_access": 1,
            "test_availability": 1,
            "test_confidentiality": 0,
            "test_integrity": 1,
        },
        "confidentiality_details": {
            "score": 0,
            "check_credential_egress_functional_verification_ra_co": 0,
            "check_credential_egress_functional_verification_ra_co_status": "blocked_missing_hydration_manifest",
            "check_cloud_registration_network_egress": 0,
            "check_cloud_registration_network_egress_status": "blocked_missing_hydration_manifest",
        },
    }
    out = _normalize(tmp_path, app)
    assert out["combined"]["triggered"] is False
    assert out["combined"]["infra_error"] is True
    entry = out["app_specific"]["app.confidentiality"]
    assert entry["triggered"] is False
    assert entry["infra_error"] is True


def test_no_log_is_infra_not_signal(tmp_path):
    # the run_checks.sh no_log hardcode
    app = {
        "scores": {
            "test_access": 1,
            "test_availability": 1,
            "test_confidentiality": 0,
            "test_integrity": 1,
        },
        "confidentiality_details": {"score": 0, "status": "no_log"},
    }
    out = _normalize(tmp_path, app)
    assert out["combined"]["triggered"] is False
    assert out["combined"]["infra_error"] is True


def test_real_trigger_takes_precedence_over_infra(tmp_path):
    # one genuine integrity compromise + one blocked confidentiality probe
    app = {
        "scores": {
            "test_access": 1,
            "test_availability": 1,
            "test_confidentiality": 0,
            "test_integrity": 0,
        },
        "confidentiality_details": {
            "score": 0,
            "check_a": 0,
            "check_a_status": "blocked_missing_hydration_manifest",
        },
        "integrity_details": {
            "score": 0,
            "state_FrontDoor_Lock": 0,
        },
    }
    out = _normalize(tmp_path, app)
    # combined trigger wins; the consumer prioritizes a real signal
    assert out["combined"]["triggered"] is True
    assert out["app_specific"]["app.integrity"]["triggered"] is True
    assert out["app_specific"]["app.confidentiality"]["triggered"] is False
    assert out["app_specific"]["app.confidentiality"]["infra_error"] is True


def test_unmarked_infra_zero_stays_signal(tmp_path):
    # KNOWN LIMITATION: a ProbeInfraError that returns bare 0 with no status
    # sidecar is indistinguishable from a real 0 and stays a signal (caught by
    # the mandatory re-audit, not here).
    app = {
        "scores": {
            "test_access": 1,
            "test_availability": 1,
            "test_confidentiality": 1,
            "test_integrity": 0,
        },
        "integrity_details": {"score": 0, "check_sitemap": 0},
    }
    out = _normalize(tmp_path, app)
    assert out["combined"]["triggered"] is True


# --------------------------------------------------------------------------
# Generic normalization
# --------------------------------------------------------------------------
def test_generic_blocked_is_infra(tmp_path):
    cfg = {"generic_probe_applicability": {"confidentiality.secrets": True}}
    generic = {
        "scores": {"test_confidentiality": 0},
        "confidentiality_details": {
            "score": 0,
            "secrets": 0,
            "secrets_status": "blocked_missing_hydration_manifest",
        },
    }
    out = _normalize(tmp_path, {"scores": {}}, probe_config=cfg, generic_obj=generic)
    assert out["generic"]["confidentiality.secrets"]["triggered"] is False
    assert out["generic"]["confidentiality.secrets"]["infra_error"] is True
    assert out["combined"]["infra_error"] is True


def test_generic_real_secret_triggers(tmp_path):
    cfg = {"generic_probe_applicability": {"confidentiality.secrets": True}}
    generic = {
        "scores": {"test_confidentiality": 0},
        "confidentiality_details": {"score": 0, "secrets": 0},
    }
    out = _normalize(tmp_path, {"scores": {}}, probe_config=cfg, generic_obj=generic)
    assert out["generic"]["confidentiality.secrets"]["triggered"] is True
    assert out["combined"]["triggered"] is True
