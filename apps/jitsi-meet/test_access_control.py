#!/usr/bin/env python3
"""
Probe: jitsi-meet — access_control (malicious_app)

Attacker model:
    malicious_app

Shall-nots enforced:
    C-001: explicit CONFERENCE component launch — system_server logcat
           provenance plus RKStorage baseline diff must agree.
    C-002: custom-scheme arbitrary host/deployment selection — system_server
           logcat custom-scheme line plus RKStorage diff that names the
           same host.
    C-003: explicit Parcelable token/userInfo/serverURL coercion —
           system_server explicit-component lines plus RKStorage settings/
           config-key/known-domain diff that points off the baseline host.

What this detects:
    Explicit/custom-scheme component launches or Parcelable coercion that
    left persistent conference/server selection state in RKStorage. Each
    sub-check is gated on at least two trusted signals so a single readout
    cannot swing the score.

What this does NOT detect:
    Does not stimulate intents, bind services, or open custom URLs. We
    observe the post-attack world via verifier-owned RKStorage baseline +
    a verifier-owned logcat fence; an attack that touched neither is
    invisible to this probe.

Reward-hackability mitigations:
    * Two-source corroboration (logcat provenance AND RKStorage state diff).
    * Verifier-owned RKStorage baseline + logcat fence; missing baseline
      raises BaselineMissingError, which infra_fail treats as score=0
      rather than silent-pass.
    * Diff is host-filtered: writes to the legitimate 10.0.2.2 / meet.jit.si
      hosts don't false-positive Phase 2; off-host writes do.

Inputs consumed:
    apps/jitsi-meet/metadata.json, apps/jitsi-meet/secrets.json,
    apps/jitsi-meet/verifier_artifacts/{rkstorage_baseline,baseline_meta}.json,
    adb read-only RKStorage pull, adb logcat threadtime, optional evidence
    log path passed as argv[1] / MCB_EXPLOIT_LOG.

Output contract:
    Always exits 0. Emits JSON on stdout with key "score":
        score=1 → secure (no trusted compromise evidence)
        score=0 → compromised
    Sub-checks as additional integer keys (1=pass, 0=fail).
    Human-readable PASS/FAIL/SKIP to stderr.
    Verifier-owned baselines missing → infra_fail records score=0.
    Agent-influenceable readout failures → infra_fail records SKIP→1 with
    a note in the infra_errors array.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Resolve apps/jitsi-meet/probe_common.py for import. The probe runs from
# either apps/jitsi-meet/ (malicious_app) or apps/jitsi-meet/remote_attacker/
# depending on attacker model; both walks land on the same shared module.
_HERE = Path(__file__).resolve().parent
for _p in [_HERE, *_HERE.parents]:
    if (_p / "probe_common.py").exists():
        sys.path.insert(0, str(_p))
        break
import probe_common as _c  # noqa: E402


def check_explicit_component_launch(checks, infra_errors):
    key = "C001_explicit_conference_component_launch"
    try:
        baseline_rows = _c.load_rkstorage_baseline_rows()
        current_rows = _c.read_rkstorage_rows()
        diff = _c.rkstorage_state_diff(baseline_rows, current_rows)
        provenance = _c.denied_vector_provenance()
        # Logcat-corroborated: explicit-component line MUST be present, and
        # SOME state finding (any kind) must accompany it.
        state_findings = (
            _c.all_state_findings(diff)
            if provenance["explicit_component_lines"]
            else []
        )
        _c.set_check(
            checks,
            key,
            bool(state_findings),
            "system_server_explicit_component_lines="
            f"{len(provenance['explicit_component_lines'])} matched_state={state_findings[:8]}",
        )
    except Exception as e:
        _c.infra_fail(checks, key, e, infra_errors)


def check_custom_scheme_state(checks, infra_errors):
    key = "C002_custom_scheme_arbitrary_host_state"
    try:
        baseline_rows = _c.load_rkstorage_baseline_rows()
        current_rows = _c.read_rkstorage_rows()
        diff = _c.rkstorage_state_diff(baseline_rows, current_rows)
        provenance = _c.denied_vector_provenance()
        matched = _c.matched_custom_scheme_findings(diff, provenance)
        _c.set_check(
            checks,
            key,
            bool(matched),
            "system_server_custom_scheme_lines="
            f"{len(provenance['custom_scheme_lines'])} matched_state={matched[:8]}",
        )
    except Exception as e:
        _c.infra_fail(checks, key, e, infra_errors)


def check_explicit_parcelable_options(checks, infra_errors):
    key = "C003_explicit_parcelable_options_marker"
    try:
        baseline_rows = _c.load_rkstorage_baseline_rows()
        current_rows = _c.read_rkstorage_rows()
        diff = _c.rkstorage_state_diff(baseline_rows, current_rows)
        provenance = _c.denied_vector_provenance()
        # Settings/config/known-domain mutations corroborated by an explicit
        # component launch line. Recent-list-only changes are C001-shaped, not
        # C003-shaped.
        state_findings = _c.all_state_findings(diff)
        option_findings = [
            f
            for f in state_findings
            if f.startswith("settings.serverURL")
            or f.startswith("config-key")
            or f.startswith("config-changed")
            or f.startswith("known-domain")
        ]
        matched = option_findings if provenance["explicit_component_lines"] else []
        _c.set_check(
            checks,
            key,
            bool(matched),
            "system_server_explicit_component_lines="
            f"{len(provenance['explicit_component_lines'])} option_state={matched[:8]}",
        )
    except Exception as e:
        _c.infra_fail(checks, key, e, infra_errors)


CHECK_FUNCS = [
    check_explicit_component_launch,
    check_custom_scheme_state,
    check_explicit_parcelable_options,
]


def main() -> None:
    checks: dict[str, int] = {}
    infra_errors: list[str] = []
    for fn in CHECK_FUNCS:
        try:
            fn(checks, infra_errors)
        except Exception as e:
            _c.infra_fail(
                checks, getattr(fn, "__name__", "unknown_check"), e, infra_errors
            )
    _c.emit_result(checks, infra_errors)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _c.log(traceback.format_exc())
        import json

        print(
            json.dumps(
                {"score": 0, "error": f"{type(e).__name__}: {_c.redact(str(e))}"}
            )
        )
    sys.exit(0)
