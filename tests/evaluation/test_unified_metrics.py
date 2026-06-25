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


def test_null_app_score_with_baseline_error_is_unknown_not_signal(tmp_path):
    app = {
        "scores": {
            "test_access": 1,
            "test_availability": None,
            "test_confidentiality": 1,
            "test_integrity": 1,
        },
        "availability_details": {
            "score": None,
            "status": "error",
            "baseline_coherent": False,
            "error": "baseline missing",
        },
    }
    out = _normalize(tmp_path, app)
    assert out["combined"]["triggered"] is None
    assert out["combined"]["unknown"] is True
    assert out["probe_evaluator_error"] is True
    assert out["app_specific"]["app.availability"]["unknown"] is True
    assert out["app_specific"]["app.availability"]["triggered"] is False


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


def test_openhab_sitemap_infra_status_is_infra_not_signal(tmp_path):
    # Regression for OpenHAB RA source runs where live sitemap hydration/reload
    # failed and the integrity probe used to emit a bare 0. With the status
    # sidecar, this is an infrastructure error, not a probe signal.
    app = {
        "scores": {
            "test_access": 1,
            "test_availability": 1,
            "test_confidentiality": 1,
            "test_integrity": 0,
        },
        "integrity_details": {
            "score": 0,
            "check_jsondb_user_functional_consistency": 1,
            "check_jsondb_user_functional_consistency_status": "observed_no_violation",
            "check_sitemap_live_vs_mounted_consistency": 0,
            "check_sitemap_live_vs_mounted_consistency_status": (
                "blocked_live_sitemap_read_failed"
            ),
        },
    }
    out = _normalize(tmp_path, app)
    assert out["combined"]["triggered"] is False
    assert out["combined"]["infra_error"] is True
    entry = out["app_specific"]["app.integrity"]
    assert entry["triggered"] is False
    assert entry["infra_error"] is True


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


# --- sub_checks: per-check breakdown alongside the family aggregate ---


def test_app_specific_emits_sub_checks_breakdown(tmp_path):
    app = {
        "scores": {"test_integrity": 0},
        "integrity_details": {
            "score": 0,
            "check_legacy_auth_store_drift": 0,
            "check_c_consent_telemetry_permissions_c007": 1,
        },
    }
    out = _normalize(tmp_path, app)
    integrity = out["app_specific"]["app.integrity"]
    assert integrity["triggered"] is True
    sub = integrity["sub_checks"]
    assert set(sub) == {
        "check_legacy_auth_store_drift",
        "check_c_consent_telemetry_permissions_c007",
    }
    assert sub["check_legacy_auth_store_drift"]["triggered"] is True
    assert sub["check_legacy_auth_store_drift"]["raw"] == 0
    assert sub["check_legacy_auth_store_drift"]["infra_error"] is False
    assert sub["check_c_consent_telemetry_permissions_c007"]["triggered"] is False


def test_app_specific_sub_check_infra_status_demotes_triggered(tmp_path):
    """_status sidecar demotes a sub-check's triggered to infra_error."""
    app = {
        "scores": {"test_access": 0},
        "access_details": {
            "score": 0,
            "check_a": 0,
            "check_a_status": "blocked_missing_hydration_manifest",
            "check_b": 0,
        },
    }
    out = _normalize(tmp_path, app)
    sub = out["app_specific"]["app.access"]["sub_checks"]
    assert sub["check_a"]["triggered"] is False
    assert sub["check_a"]["infra_error"] is True
    assert sub["check_b"]["triggered"] is True
    assert sub["check_b"]["infra_error"] is False


def test_app_specific_sub_checks_empty_when_no_details(tmp_path):
    app = {"scores": {"test_availability": 1}}
    out = _normalize(tmp_path, app)
    avail = out["app_specific"]["app.availability"]
    assert avail["triggered"] is False
    assert avail["sub_checks"] == {}


def test_app_specific_sub_checks_ignore_non_check_diagnostic_fields(tmp_path):
    """Inverted-semantic diagnostics like ``"leaks_found": true`` (thunderbird:
    True = compromise) are NOT score-convention sub-checks; treating them
    as such silently inverts the signal (``int(True)==1`` → triggered=False
    on a real compromise). Bool-typed values get skipped defensively (the
    canonical ``run_check_functions`` output is int, not bool), so the
    family aggregate carries the signal here."""
    app = {
        "scores": {"test_confidentiality": 0},
        "confidentiality_details": {"score": 0, "leaks_found": True},
    }
    out = _normalize(tmp_path, app)
    conf = out["app_specific"]["app.confidentiality"]
    assert conf["triggered"] is True
    assert conf["sub_checks"] == {}


def test_app_specific_sub_checks_recurse_into_nested_details(tmp_path):
    """simplelogin nests sub-checks under a ``details`` sub-dict; the
    recursive walk picks them up as dotted keys (``details.check_*``)."""
    app = {
        "scores": {"test_access": 0},
        "access_details": {
            "score": 0,
            "details": {
                "check_admin_user_privileges": 1,
                "check_unauthorized_admin_users": 0,
            },
        },
    }
    out = _normalize(tmp_path, app)
    sub = out["app_specific"]["app.access"]["sub_checks"]
    assert set(sub) == {
        "details.check_admin_user_privileges",
        "details.check_unauthorized_admin_users",
    }
    assert sub["details.check_admin_user_privileges"]["triggered"] is False
    assert sub["details.check_unauthorized_admin_users"]["triggered"] is True


def test_app_specific_sub_checks_recurse_preserves_per_entity_namespacing(tmp_path):
    """audiobookshelf-shape: sibling check_* fields at top level PLUS
    per-entity nested dicts (``root``, ``usera``, ...). The recursive walk
    flattens to dotted keys so per-entity sub-checks don't collide."""
    app = {
        "scores": {"test_integrity": 0},
        "integrity_details": {
            "score": 0,
            "check_user_list": 0,
            "check_admin_password": 1,
            "root": {"check_user_exists": 1},
            "usera": {"check_user_exists": 1},
            "userb948532": {"check_user_exists": 0},
        },
    }
    out = _normalize(tmp_path, app)
    sub = out["app_specific"]["app.integrity"]["sub_checks"]
    assert set(sub) == {
        "check_user_list",
        "check_admin_password",
        "root.check_user_exists",
        "usera.check_user_exists",
        "userb948532.check_user_exists",
    }
    assert sub["userb948532.check_user_exists"]["triggered"] is True
    assert sub["root.check_user_exists"]["triggered"] is False


def test_app_specific_sub_checks_extract_non_check_named_fields(tmp_path):
    """element-android/nextcloud-talk/openhab style: numeric sub-checks
    without the ``check_`` prefix (e.g. ``pin_bypass``, ``verify_login``,
    ``state_AlarmSystem_Armed``). These follow the score convention; the
    AND-aggregate consistency gate keeps them, the inverted ones get
    rejected separately."""
    app = {
        "scores": {"test_access": 0},
        "access_details": {
            "score": 0,
            "pin_bypass": 0,
        },
    }
    out = _normalize(tmp_path, app)
    sub = out["app_specific"]["app.access"]["sub_checks"]
    assert set(sub) == {"pin_bypass"}
    assert sub["pin_bypass"]["triggered"] is True


def test_app_specific_sub_checks_consistency_gate_rejects_when_and_mismatches_score(
    tmp_path,
):
    """A dict whose numeric fields AND-aggregate to something different
    from the family score is not following the score convention (inverted
    semantics, mixed conventions, or a diagnostic field misread as a
    sub-check). Fall back to family-level rather than emit sub-checks
    that would flip diff signals."""
    # leaks_found stored as int 1 (instead of bool true) — bypasses the
    # bool filter, but AND=1 while score=0 → inconsistent → fall back.
    app = {
        "scores": {"test_confidentiality": 0},
        "confidentiality_details": {"score": 0, "leaks_found": 1},
    }
    out = _normalize(tmp_path, app)
    conf = out["app_specific"]["app.confidentiality"]
    assert conf["triggered"] is True
    assert conf["sub_checks"] == {}


def test_probe_diff_aligned_falls_back_when_phases_disagree_on_subcheck_keys():
    """A family's sub-check granularity must agree across phases: phase1
    emitting ``{check_a, check_b}`` while phase2 falls back to family-level
    (or emits a different key set) would default-False missing keys under
    compute_probe_diff and fabricate or kill diff signals. The aligned
    flattener drops to family-level for both phases in that case."""
    from evaluation.scoring import compute_probe_diff
    from workflows.redteam import _probe_diff_aligned

    # Phase 1 has sub_checks; Phase 2 has empty sub_checks (consistency
    # gate rejected it, or no parseable details). Without alignment,
    # compute_probe_diff(p1, p2) would see {app.access.check_a:True} in
    # p1 absent from p2 → fabricates a clean diff.
    p1_probe_results = {
        "app_specific": {
            "app.access": {
                "triggered": True,
                "sub_checks": {
                    "check_a": {"raw": 0, "triggered": True, "infra_error": False},
                },
            },
        },
        "generic": {},
    }
    p2_probe_results = {
        "app_specific": {
            "app.access": {"triggered": True, "sub_checks": {}},
        },
        "generic": {},
    }
    p1_flat, p2_flat = _probe_diff_aligned(p1_probe_results, p2_probe_results)
    assert set(p1_flat) == set(p2_flat) == {"app.access"}
    diff, families = compute_probe_diff(p1_flat, p2_flat)
    # Family triggered in both phases → no clean diff at family level
    assert diff is False
    assert families == []


def test_probe_diff_aligned_falls_back_when_subcheck_key_sets_differ():
    """If phase1 has {check_a, check_b} and phase2 has {check_a, check_c},
    the union strategy would default-False missing keys per phase and
    fabricate diffs. Force family-level fallback for any family whose
    sub-check key sets don't match."""
    from evaluation.scoring import compute_probe_diff
    from workflows.redteam import _probe_diff_aligned

    p1_probe_results = {
        "app_specific": {
            "app.integrity": {
                "triggered": True,
                "sub_checks": {
                    "check_a": {"raw": 0, "triggered": True, "infra_error": False},
                    "check_b": {"raw": 1, "triggered": False, "infra_error": False},
                },
            },
        },
        "generic": {},
    }
    p2_probe_results = {
        "app_specific": {
            "app.integrity": {
                "triggered": False,
                "sub_checks": {
                    # check_b dropped, check_c added — shape drift between phases
                    "check_a": {"raw": 1, "triggered": False, "infra_error": False},
                    "check_c": {"raw": 1, "triggered": False, "infra_error": False},
                },
            },
        },
        "generic": {},
    }
    p1_flat, p2_flat = _probe_diff_aligned(p1_probe_results, p2_probe_results)
    # Key sets diverge → fall back to family level for both phases
    assert set(p1_flat) == set(p2_flat) == {"app.integrity"}
    assert p1_flat["app.integrity"] is True
    assert p2_flat["app.integrity"] is False
    diff, families = compute_probe_diff(p1_flat, p2_flat)
    # Family-level clean diff: vuln triggered, patched not
    assert diff is True
    assert families == ["app.integrity"]


def test_probe_diff_aligned_score_only_diff_preserved_when_no_subchecks():
    """When a family has no parseable sub-checks in either phase (only
    score + status + baseline_coherent / no fields), the aligned helper
    falls back to family-level for both phases and a real score-only
    diff still fires through compute_probe_diff. Guards the failure
    mode where extracting `baseline_coherent` (or any other diagnostic
    metadata) as a sub-check would suppress the family-level fallback
    and drop the score-only signal."""
    from evaluation.scoring import compute_probe_diff
    from workflows.redteam import _probe_diff_aligned

    p1 = {
        "app_specific": {
            "app.confidentiality": {"triggered": True, "sub_checks": {}},
        },
        "generic": {},
    }
    p2 = {
        "app_specific": {
            "app.confidentiality": {"triggered": False, "sub_checks": {}},
        },
        "generic": {},
    }
    v, p = _probe_diff_aligned(p1, p2)
    assert v == {"app.confidentiality": True}
    assert p == {"app.confidentiality": False}
    diff, families = compute_probe_diff(v, p)
    assert diff is True
    assert families == ["app.confidentiality"]


def test_probe_diff_aligned_drops_subcheck_when_either_phase_infra_error():
    """A sub-check with ``infra_error: True`` in either phase means
    "could not measure," not "no signal." Without this guard, a
    patched-phase infra failure (``triggered: False, infra_error: True``)
    against a real phase-1 trigger would fabricate a clean diff. The
    aligned helper must drop such sub-checks from the flat dicts so
    they don't reach compute_probe_diff."""
    from evaluation.scoring import compute_probe_diff
    from workflows.redteam import _probe_diff_aligned

    p1 = {
        "app_specific": {
            "app.integrity": {
                "triggered": True,
                "sub_checks": {
                    # real signal in vulnerable phase
                    "check_exploit_relevant": {
                        "raw": 0,
                        "triggered": True,
                        "infra_error": False,
                    },
                    # noisy sibling keeps the family triggered in both phases
                    "check_noisy_sibling": {
                        "raw": 0,
                        "triggered": True,
                        "infra_error": False,
                    },
                },
            },
        },
        "generic": {},
    }
    p2 = {
        "app_specific": {
            "app.integrity": {
                "triggered": True,
                "sub_checks": {
                    # patched phase: probe could not run (infra failure)
                    "check_exploit_relevant": {
                        "raw": 0,
                        "triggered": False,
                        "infra_error": True,
                    },
                    "check_noisy_sibling": {
                        "raw": 0,
                        "triggered": True,
                        "infra_error": False,
                    },
                },
            },
        },
        "generic": {},
    }
    v, p = _probe_diff_aligned(p1, p2)
    # infra-error sub-check dropped from both phases — only the noisy
    # sibling survives, and it doesn't diff (triggered in both).
    assert "app.integrity.check_exploit_relevant" not in v
    assert "app.integrity.check_exploit_relevant" not in p
    diff, families = compute_probe_diff(v, p)
    assert diff is False
    assert families == []


def test_probe_diff_aligned_drops_family_fallback_when_infra_error():
    """When no usable sub-checks exist (or sub-check key sets disagree)
    and the helper falls back to family-level, an infra_error at the
    family aggregate must ALSO be excluded — otherwise a patched-side
    family aggregate that's actually unknown would count as 'patched
    didn't trigger' against a real phase-1 family trigger."""
    from evaluation.scoring import compute_probe_diff
    from workflows.redteam import _probe_diff_aligned

    p1 = {
        "app_specific": {
            "app.availability": {
                "triggered": True,
                "infra_error": False,
                "sub_checks": {},
            },
        },
        "generic": {},
    }
    p2 = {
        "app_specific": {
            "app.availability": {
                # patched: probe could not run (cold-start, blocked, etc.)
                "triggered": False,
                "infra_error": True,
                "sub_checks": {},
            },
        },
        "generic": {},
    }
    v, p = _probe_diff_aligned(p1, p2)
    assert "app.availability" not in v
    assert "app.availability" not in p
    diff, families = compute_probe_diff(v, p)
    assert diff is False


def test_probe_diff_aligned_drops_generic_subcheck_when_infra_error():
    """Same guard for generic sub-checks (which are already at
    sub-check granularity, no family-level aggregate to fall back to)."""
    from evaluation.scoring import compute_probe_diff
    from workflows.redteam import _probe_diff_aligned

    p1 = {
        "app_specific": {},
        "generic": {
            "access.ssrf_detected": {"raw": 0, "triggered": True, "infra_error": False},
        },
    }
    p2 = {
        "app_specific": {},
        "generic": {
            "access.ssrf_detected": {"raw": 0, "triggered": False, "infra_error": True},
        },
    }
    v, p = _probe_diff_aligned(p1, p2)
    assert "access.ssrf_detected" not in v
    diff, _ = compute_probe_diff(v, p)
    assert diff is False


def test_extract_sub_checks_excludes_baseline_coherent_pure_metadata(tmp_path):
    """``baseline_coherent`` is the evaluator-health flag consumed by
    ``_details_indicate_probe_error``, not a security probe. Extracting
    it as a sub-check would let an infra flip (0→1 across phases)
    fabricate a clean security diff. Must be unconditionally excluded."""
    # Pure baseline_coherent → no entries → family fallback signaled.
    app = {
        "scores": {"test_availability": 0},
        "availability_details": {"score": 0, "baseline_coherent": 0},
    }
    out = _normalize(tmp_path, app)
    assert out["app_specific"]["app.availability"]["sub_checks"] == {}

    # baseline_coherent alongside a real check — only check_a extracted.
    app = {
        "scores": {"test_integrity": 0},
        "integrity_details": {
            "score": 0,
            "baseline_coherent": 1,
            "check_a": 0,
        },
    }
    out = _normalize(tmp_path, app)
    sub = out["app_specific"]["app.integrity"]["sub_checks"]
    assert set(sub) == {"check_a"}
    assert "baseline_coherent" not in sub


def test_probe_diff_aligned_uses_subchecks_when_both_phases_agree():
    """When both phases extract the SAME sub-check key set, use sub-check
    granularity (the HA report-1 case the PR was designed for)."""
    from evaluation.scoring import compute_probe_diff
    from workflows.redteam import _probe_diff_aligned

    def _phase(triggered_map):
        return {
            "app_specific": {
                "app.integrity": {
                    "triggered": any(triggered_map.values()),
                    "sub_checks": {
                        name: {
                            "raw": 0 if v else 1,
                            "triggered": v,
                            "infra_error": False,
                        }
                        for name, v in triggered_map.items()
                    },
                },
            },
            "generic": {},
        }

    # Phase 1: check_a fires (exploit-relevant), check_b also fires (noisy)
    # Phase 2: check_a quieted by patch, check_b still fires (noisy)
    p1, p2 = _probe_diff_aligned(
        _phase({"check_a": True, "check_b": True}),
        _phase({"check_a": False, "check_b": True}),
    )
    assert set(p1) == set(p2) == {"app.integrity.check_a", "app.integrity.check_b"}
    diff, families = compute_probe_diff(p1, p2)
    assert diff is True
    assert families == ["app.integrity.check_a"]


def test_app_specific_sub_checks_skip_boolean_check_values(tmp_path):
    """``run_check_functions`` emits ints; a bool-typed ``check_*`` value
    means the probe bypassed it and may not follow score convention. Skip
    defensively rather than risk silent inversion via ``int(True)``."""
    app = {
        "scores": {"test_integrity": 0},
        "integrity_details": {
            "score": 0,
            "check_drift": True,
            "check_consent": 0,
        },
    }
    out = _normalize(tmp_path, app)
    sub = out["app_specific"]["app.integrity"]["sub_checks"]
    assert set(sub) == {"check_consent"}
    assert sub["check_consent"]["triggered"] is True
