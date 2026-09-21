"""Pipeline unit tests.

Stdlib unittest, no external deps. Run via::

    python -m unittest discover probe_gen/tests
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from probe_gen.pipeline.archetypes import (
    get_archetype,
    list_archetypes,
    list_known_apps,
)
from probe_gen.pipeline.models import (
    CVSSv31,
    DecoyAttempt,
    GateResult,
    Invariant,
    Probe,
    ProbeGenRun,
    SyntheticVulnerability,
)
from probe_gen.pipeline.probes import (
    ANTI_PATTERN_CATALOGUE,
    ProbeBody,
    make_minimal_probe,
    render_probe_source,
)
from probe_gen.pipeline.prompts import (
    ALL_PROMPTS,
    PromptTemplate,
    get_prompt,
)


def _sample_invariant() -> Invariant:
    return Invariant(
        invariant_id="RA-C",
        statement="Companion APK shall not contain credentials authenticating as a privileged user.",
        attacker_model="remote_attacker",
        cwe_ids=["CWE-798"],
        cvss=CVSSv31(
            vector="CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:N",
            base_score=8.1,
            severity="HIGH",
            rationale="credential extraction enables admin impersonation",
        ),
        threat_model_anchor="threat_model.md#shall-not-ra-c",
        linked_historic_cves=[],
    )


class TestModelsRoundTrip(unittest.TestCase):
    def test_invariant_round_trip(self) -> None:
        inv = _sample_invariant()
        d = inv.to_dict()
        # Must be JSON-serializable
        json_str = json.dumps(d)
        d2 = json.loads(json_str)
        inv2 = Invariant.from_dict(d2)
        self.assertEqual(inv, inv2)

    def test_invariant_round_trip_no_cvss(self) -> None:
        inv = _sample_invariant()
        inv.cvss = None
        d = inv.to_dict()
        inv2 = Invariant.from_dict(d)
        self.assertEqual(inv, inv2)
        self.assertIsNone(inv2.cvss)

    def test_probe_round_trip(self) -> None:
        inv = _sample_invariant()
        p = make_minimal_probe(inv, channel="auth-store-diff", category="access")
        d = p.to_dict()
        json.dumps(d)  # JSON-serializable
        p2 = Probe.from_dict(d)
        self.assertEqual(p, p2)

    def test_synthetic_vuln_round_trip(self) -> None:
        cvss = CVSSv31(
            vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:N",
            base_score=7.5,
            severity="HIGH",
            rationale="impersonation",
        )
        sv = SyntheticVulnerability(
            vuln_id="vuln_0",
            target_invariant_id="RA-C",
            title="XMPP Carbon Copy Impersonation",
            historic_cve="CVE-2025-27916",
            cwe_id="CWE-290",
            cwe_name="Authentication Bypass by Spoofing",
            cvss_historic=cvss,
            cvss_synthetic=cvss,
            attacker_model="remote_attacker",
        )
        d = sv.to_dict()
        json.dumps(d)
        sv2 = SyntheticVulnerability.from_dict(d)
        self.assertEqual(sv, sv2)

    def test_probe_gen_run_serialization(self) -> None:
        run = ProbeGenRun(
            run_id="test_run",
            app="conversations",
            started_at_iso="2026-04-30T15:00:00Z",
            invariants_proposed=[_sample_invariant()],
            gate_results=[
                GateResult(
                    gate="clean_baseline",
                    outcome="pass",
                    duration_seconds=1.2,
                    artifact_id="check_x",
                    artifact_kind="probe",
                )
            ],
            decoy_attempts=[
                DecoyAttempt(
                    decoy_class="artifact_forgery",
                    model_family="claude",
                    against_artifact="check_x",
                    succeeded=False,
                )
            ],
        )
        d = run.to_dict()
        # must be json-serializable
        json.dumps(d)


class TestArchetypes(unittest.TestCase):
    def test_all_30_apps_tagged(self) -> None:
        # 30 apps under apps/ as of audit; archetype assignments must be exhaustive
        # for those 30. Source of truth = audit script output, but we check at
        # least the tagged set is non-empty and apps are non-overlapping.
        apps = list_known_apps()
        self.assertEqual(len(apps), 30)
        # Each app appears in exactly one archetype
        all_apps_with_dups = [a for prof in list_archetypes() for a in prof.apps]
        self.assertEqual(sorted(all_apps_with_dups), sorted(apps))

    def test_pilot_apps_have_archetype(self) -> None:
        for app in ("conversations", "openvpn"):
            prof = get_archetype(app)
            self.assertGreater(len(prof.invariant_templates), 0)

    def test_archetype_invariant_templates_cover_pilot_classes(self) -> None:
        # Conversations (messaging) must have at least the impersonation template
        # — the canonical example bug from vuln_0.
        prof = get_archetype("conversations")
        template_ids = [t.template_id for t in prof.invariant_templates]
        self.assertIn("messaging.identity_no_impersonation", template_ids)

        # OpenVPN (security_network) must have cert-validation
        prof2 = get_archetype("openvpn")
        template_ids2 = [t.template_id for t in prof2.invariant_templates]
        self.assertIn("netsec.cert_validation_required", template_ids2)


class TestProbeRendering(unittest.TestCase):
    def test_rendered_probe_is_valid_python(self) -> None:
        inv = _sample_invariant()
        probe = make_minimal_probe(
            inv,
            channel="auth-store-diff",
            category="access",
            primitives=["docker_running", "load_baseline"],
        )
        body = ProbeBody(
            imports_from_probe_lib=["docker_running", "load_baseline"],
            check_body='    return True, "ok"',
            citations=[],
        )
        src = render_probe_source(inv, probe, body)
        # Must parse as Python
        ast.parse(src)

    def test_rendered_probe_contains_required_sections(self) -> None:
        inv = _sample_invariant()
        probe = make_minimal_probe(
            inv,
            channel="auth-store-diff",
            category="access",
            primitives=["docker_running"],
            anti_patterns=["probe-runs-the-exploit", "probe-without-baseline"],
        )
        body = ProbeBody(
            imports_from_probe_lib=["docker_running"],
            check_body='    return True, "ok"',
        )
        src = render_probe_source(inv, probe, body)
        self.assertIn("Shall-not enforced: RA-C", src)
        self.assertIn("Channel: auth-store-diff.", src)
        self.assertIn("Attacker model: remote_attacker.", src)
        self.assertIn("Category: access.", src)
        self.assertIn("Anti-pattern declarations:", src)
        self.assertIn("1. probe-runs-the-exploit:", src)
        self.assertIn("2. probe-without-baseline:", src)
        self.assertIn("from probe_lib import docker_running", src)
        self.assertIn("from probe_lib import emit_check_result", src)
        self.assertIn("def check_ra_c_auth_store_diff", src)
        self.assertIn('if __name__ == "__main__":', src)

    def test_unknown_anti_pattern_rejected(self) -> None:
        inv = _sample_invariant()
        probe = make_minimal_probe(
            inv,
            channel="x",
            category="access",
            anti_patterns=["this-is-not-a-real-key"],
        )
        body = ProbeBody(imports_from_probe_lib=[], check_body='    return True, "ok"')
        with self.assertRaises(ValueError):
            render_probe_source(inv, probe, body)

    def test_probe_id_validation(self) -> None:
        inv = _sample_invariant()
        bad_probe = Probe(
            probe_id="not_a_check_prefix",
            invariant_id="RA-C",
            channel="x",
            attacker_model="remote_attacker",
            category="access",
        )
        body = ProbeBody(imports_from_probe_lib=[], check_body='    return True, "ok"')
        with self.assertRaises(ValueError):
            render_probe_source(inv, bad_probe, body)

    def test_anti_pattern_catalogue_entries_are_complete(self) -> None:
        # Every entry must have a non-empty description
        for key, val in ANTI_PATTERN_CATALOGUE.items():
            self.assertTrue(val.strip(), f"empty description for {key}")
        # Specific anti-patterns from canonical HA probe must be in catalogue
        for k in (
            "grep-for-vulnerable-code",
            "regex-match-without-verification",
            "probe-runs-the-exploit",
            "probe-checks-for-payload-strings",
            "probe-trusts-self-report",
            "probe-without-baseline",
            "probe-without-attacker-model-tag",
            "two-probes-one-channel",
            "brittle-substring-on-tool-output",
        ):
            self.assertIn(k, ANTI_PATTERN_CATALOGUE)


class TestRenderedProbeSyntaxAcrossArchetypes(unittest.TestCase):
    def test_render_for_each_archetype_template(self) -> None:
        # For every template in every archetype, render a stub probe and confirm
        # it parses as valid Python. Catches regressions in scaffolder when
        # invariant fields contain quotes, em-dashes, etc.
        for prof in list_archetypes():
            for tpl in prof.invariant_templates:
                inv = Invariant(
                    invariant_id=tpl.template_id.upper().replace(".", "-")[:24],
                    statement=tpl.statement_template,
                    attacker_model="remote_attacker",
                    cwe_ids=tpl.cwe_classes,
                )
                probe = make_minimal_probe(inv, channel="db-diff", category="access")
                body = ProbeBody(
                    imports_from_probe_lib=["dummy"],
                    check_body='    return True, "ok"',
                )
                src = render_probe_source(inv, probe, body)
                try:
                    ast.parse(src)
                except SyntaxError as e:  # pragma: no cover - diagnostic
                    self.fail(f"{tpl.template_id} produced invalid Python: {e}")


class TestRubricInvariants(unittest.TestCase):
    """Mechanical checks that scaffold defaults match the DESIGN.md rubrics."""

    def test_default_probe_is_diff_based_and_observer_only(self) -> None:
        inv = _sample_invariant()
        p = make_minimal_probe(inv, channel="x", category="access")
        self.assertTrue(p.diff_based)
        self.assertTrue(p.observer_only)

    def test_default_probe_declares_minimum_anti_patterns(self) -> None:
        inv = _sample_invariant()
        p = make_minimal_probe(inv, channel="x", category="access")
        # Probe rubric requires at least the no-exploit, baseline, and
        # attacker-model-tag declarations.
        self.assertIn("probe-runs-the-exploit", p.anti_patterns_avoided)
        self.assertIn("probe-without-baseline", p.anti_patterns_avoided)
        self.assertIn("probe-without-attacker-model-tag", p.anti_patterns_avoided)


class TestAuditScriptOutputConsistency(unittest.TestCase):
    """Ensure the audit script's view of apps is consistent with archetypes.py.

    If apps/ contains an app that has metadata.json but no archetype
    assignment, that's an onboarding gap the pipeline should surface.
    """

    def test_every_audited_app_has_archetype_or_is_known_pending(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        apps_dir = repo_root / "apps"
        if not apps_dir.is_dir():
            self.skipTest("apps/ directory not present in this checkout")
        actual_apps = sorted(
            d.name
            for d in apps_dir.iterdir()
            if d.is_dir() and (d / "metadata.json").is_file()
        )
        tagged = set(list_known_apps())
        untagged = [a for a in actual_apps if a not in tagged]
        self.assertEqual(
            untagged,
            [],
            f"Apps with metadata.json but no archetype tag: {untagged}. "
            "Update probe_gen/pipeline/archetypes.py.",
        )


def _import_materializer():
    """Make scripts/ importable + return the materialize_probe_spec module.

    Idempotent — safe to call from each test method.
    """
    import sys as _sys
    from pathlib import Path as _Path

    repo_root = _Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "probe_gen" / "scripts"
    if str(scripts_dir) not in _sys.path:
        _sys.path.insert(0, str(scripts_dir))
    if "materialize_probe_spec" in _sys.modules:
        del _sys.modules["materialize_probe_spec"]
    import materialize_probe_spec  # type: ignore[import-not-found]

    return materialize_probe_spec


class TestSpecValidation(unittest.TestCase):
    """validate_* enforces the rubrics from DESIGN.md."""

    def _good_invariant(self) -> Invariant:
        return Invariant(
            invariant_id="RA-1",
            statement="An attacker shall not be able to do X.",
            attacker_model="remote_attacker",
            cwe_ids=["CWE-285"],
            cvss=CVSSv31(
                vector="CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:N",
                base_score=8.1,
                severity="HIGH",
                rationale="impersonation enables RCE",
            ),
            linked_historic_cves=["CVE-2025-1234"],
        )

    def test_good_invariant_validates(self) -> None:
        from probe_gen.pipeline.validation import validate_invariant

        self.assertEqual(validate_invariant(self._good_invariant()), [])

    def test_invariant_missing_shall_not_warns(self) -> None:
        from probe_gen.pipeline.validation import validate_invariant

        inv = self._good_invariant()
        inv.statement = "An attacker can do X."
        problems = validate_invariant(inv)
        self.assertTrue(any("shall not" in p for p in problems))

    def test_invariant_bad_cwe_format_rejected(self) -> None:
        from probe_gen.pipeline.validation import validate_invariant

        inv = self._good_invariant()
        inv.cwe_ids = ["CWE285", "cwe-79"]
        problems = validate_invariant(inv)
        self.assertEqual(len(problems), 2)
        self.assertTrue(all("invalid CWE id" in p for p in problems))

    def test_invariant_cvss_score_out_of_range_rejected(self) -> None:
        from probe_gen.pipeline.validation import validate_invariant

        inv = self._good_invariant()
        assert inv.cvss is not None
        inv.cvss.base_score = 11.5
        problems = validate_invariant(inv)
        self.assertTrue(any("out of [0,10]" in p for p in problems))

    def test_probe_missing_required_anti_pattern_rejected(self) -> None:
        from probe_gen.pipeline.validation import validate_probe

        probe = Probe(
            probe_id="check_x",
            invariant_id="RA-1",
            channel="db-diff",
            attacker_model="remote_attacker",
            category="access",
            anti_patterns_avoided=["probe-runs-the-exploit"],  # missing two
        )
        problems = validate_probe(probe)
        self.assertTrue(
            any("probe-without-baseline" in p for p in problems),
            f"problems: {problems}",
        )
        self.assertTrue(any("probe-without-attacker-model-tag" in p for p in problems))

    def test_probe_unknown_anti_pattern_rejected(self) -> None:
        from probe_gen.pipeline.validation import validate_probe

        probe = Probe(
            probe_id="check_x",
            invariant_id="RA-1",
            channel="db-diff",
            attacker_model="remote_attacker",
            category="access",
            anti_patterns_avoided=[
                "probe-runs-the-exploit",
                "probe-without-baseline",
                "probe-without-attacker-model-tag",
                "this-is-made-up",
            ],
        )
        problems = validate_probe(probe)
        self.assertTrue(any("not in catalogue" in p for p in problems))

    def test_probe_bad_id_prefix_rejected(self) -> None:
        from probe_gen.pipeline.validation import validate_probe

        probe = Probe(
            probe_id="not_a_check_prefix",
            invariant_id="RA-1",
            channel="db-diff",
            attacker_model="remote_attacker",
            category="access",
        )
        problems = validate_probe(probe)
        self.assertTrue(any("check_" in p for p in problems))

    def test_probe_observer_only_required(self) -> None:
        from probe_gen.pipeline.validation import validate_probe

        probe = Probe(
            probe_id="check_x",
            invariant_id="RA-1",
            channel="x",
            attacker_model="remote_attacker",
            category="access",
            anti_patterns_avoided=list(
                [
                    "probe-runs-the-exploit",
                    "probe-without-baseline",
                    "probe-without-attacker-model-tag",
                ]
            ),
            observer_only=False,
        )
        problems = validate_probe(probe)
        self.assertTrue(any("observer_only" in p for p in problems))

    def test_synthetic_vuln_cvss_axes_must_match(self) -> None:
        from probe_gen.pipeline.validation import validate_synthetic_vulnerability

        sv = SyntheticVulnerability(
            vuln_id="vuln_0",
            target_invariant_id="RA-1",
            title="Test vuln",
            historic_cve="CVE-2025-1234",
            cwe_id="CWE-285",
            cwe_name="Authorization",
            cvss_historic=CVSSv31(
                vector="CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:N",
                base_score=8.1,
                severity="HIGH",
            ),
            cvss_synthetic=CVSSv31(
                # AV differs from historic — should be flagged
                vector="CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:N",
                base_score=7.0,
                severity="HIGH",
            ),
            attacker_model="remote_attacker",
        )
        problems = validate_synthetic_vulnerability(sv)
        self.assertTrue(any("AV=" in p and "differs" in p for p in problems))

    def test_synthetic_vuln_score_delta_too_large_flagged(self) -> None:
        from probe_gen.pipeline.validation import validate_synthetic_vulnerability

        sv = SyntheticVulnerability(
            vuln_id="vuln_0",
            target_invariant_id="RA-1",
            title="Test vuln",
            historic_cve="CVE-2025-1234",
            cwe_id="CWE-285",
            cwe_name="Authorization",
            cvss_historic=CVSSv31(
                vector="CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:N",
                base_score=8.1,
                severity="HIGH",
            ),
            cvss_synthetic=CVSSv31(
                vector="CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:N",
                base_score=4.0,  # >2 below
                severity="MEDIUM",
            ),
            attacker_model="remote_attacker",
        )
        problems = validate_synthetic_vulnerability(sv)
        self.assertTrue(any("deviates from historic" in p for p in problems))

    def test_validate_spec_cross_references(self) -> None:
        from probe_gen.pipeline.validation import validate_spec

        spec = {
            "schema_version": 1,
            "app": "x",
            "invariants": [self._good_invariant().to_dict()],
            "probes": [
                {
                    "spec": Probe(
                        probe_id="check_x",
                        invariant_id="RA-NOT-DEFINED",
                        channel="db",
                        attacker_model="remote_attacker",
                        category="access",
                        anti_patterns_avoided=[
                            "probe-runs-the-exploit",
                            "probe-without-baseline",
                            "probe-without-attacker-model-tag",
                        ],
                    ).to_dict(),
                    "body": {
                        "imports_from_probe_lib": [],
                        "check_body": '    return True, "ok"',
                    },
                }
            ],
        }
        problems = validate_spec(spec)
        self.assertTrue(any("unknown invariant" in p for p in problems))

    def test_assert_no_problems_raises_on_issues(self) -> None:
        from probe_gen.pipeline.validation import assert_no_problems

        with self.assertRaises(ValueError):
            assert_no_problems(["something is wrong"])
        # Empty list should not raise
        assert_no_problems([])


class TestMaterializer(unittest.TestCase):
    """Verifies the spec→file pipeline produces parseable check_*.py output."""

    def test_materialize_dry_run_returns_plan_no_writes(self) -> None:
        import tempfile
        from pathlib import Path as _Path

        materialize_probe_spec = _import_materializer()

        with tempfile.TemporaryDirectory() as tmp:
            target = _Path(tmp) / "appdir"
            spec = {
                "schema_version": 1,
                "app": "testapp",
                "invariants": [
                    {
                        "invariant_id": "X-1",
                        "statement": "Test shall not.",
                        "attacker_model": "remote_attacker",
                        "cwe_ids": ["CWE-285"],
                        "cvss": None,
                        "linked_historic_cves": [],
                        "threat_model_anchor": "",
                        "notes": "",
                    }
                ],
                "probes": [
                    {
                        "spec": {
                            "probe_id": "check_x_1_db",
                            "invariant_id": "X-1",
                            "channel": "db",
                            "attacker_model": "remote_attacker",
                            "category": "access",
                            "primitives_used": [],
                            "anti_patterns_avoided": ["probe-runs-the-exploit"],
                            "diff_based": True,
                            "observer_only": True,
                            "source_path": "",
                            "notes": "",
                        },
                        "body": {
                            "imports_from_probe_lib": [],
                            "check_body": '    return True, "ok"',
                            "citations": [],
                        },
                    }
                ],
            }
            plan = materialize_probe_spec.materialize(
                spec, target, apply=False, skip_rubric_validation=True
            )
            self.assertEqual(len(plan), 1)
            path, content = plan[0]
            # Path resolves under remote_attacker/checks/
            self.assertEqual(path.parent.name, "checks")
            self.assertEqual(path.parent.parent.name, "remote_attacker")
            # No file actually written
            self.assertFalse(path.is_file())
            # Body is valid Python
            ast.parse(content)
            self.assertIn("Shall-not enforced: X-1", content)

    def test_materialize_apply_writes_files(self) -> None:
        import tempfile
        from pathlib import Path as _Path

        materialize_probe_spec = _import_materializer()

        with tempfile.TemporaryDirectory() as tmp:
            target = _Path(tmp) / "appdir"
            spec = {
                "schema_version": 1,
                "app": "testapp",
                "invariants": [
                    {
                        "invariant_id": "X-1",
                        "statement": "Test shall not.",
                        "attacker_model": "malicious_app",
                        "cwe_ids": ["CWE-285"],
                        "cvss": None,
                        "linked_historic_cves": [],
                        "threat_model_anchor": "",
                        "notes": "",
                    }
                ],
                "probes": [
                    {
                        "spec": {
                            "probe_id": "check_x_1",
                            "invariant_id": "X-1",
                            "channel": "filesystem",
                            "attacker_model": "malicious_app",
                            "category": "integrity",
                            "primitives_used": [],
                            "anti_patterns_avoided": ["probe-runs-the-exploit"],
                            "diff_based": True,
                            "observer_only": True,
                            "source_path": "",
                            "notes": "",
                        },
                        "body": {
                            "imports_from_probe_lib": [],
                            "check_body": '    return True, "ok"',
                            "citations": [],
                        },
                    }
                ],
            }
            plan = materialize_probe_spec.materialize(
                spec, target, apply=True, skip_rubric_validation=True
            )
            self.assertEqual(len(plan), 1)
            path, _ = plan[0]
            # malicious_app probes go under checks/, not remote_attacker/checks/
            self.assertEqual(path.parent.name, "checks")
            self.assertNotEqual(path.parent.parent.name, "remote_attacker")
            self.assertTrue(path.is_file())
            ast.parse(path.read_text(encoding="utf-8"))

    def test_materialize_rejects_unknown_invariant_reference(self) -> None:
        import tempfile
        from pathlib import Path as _Path

        materialize_probe_spec = _import_materializer()

        with tempfile.TemporaryDirectory() as tmp:
            target = _Path(tmp) / "appdir"
            bad_spec = {
                "schema_version": 1,
                "app": "testapp",
                "invariants": [],  # empty
                "probes": [
                    {
                        "spec": {
                            "probe_id": "check_orphan",
                            "invariant_id": "DOES-NOT-EXIST",
                            "channel": "x",
                            "attacker_model": "remote_attacker",
                            "category": "access",
                        },
                        "body": {
                            "imports_from_probe_lib": [],
                            "check_body": '    return True, "ok"',
                        },
                    }
                ],
            }
            with self.assertRaises(ValueError):
                materialize_probe_spec.materialize(bad_spec, target, apply=False)


class TestPrompts(unittest.TestCase):
    def test_all_prompts_have_required_fields(self) -> None:
        self.assertGreater(len(ALL_PROMPTS), 0)
        for name, prompt in ALL_PROMPTS.items():
            self.assertIsInstance(prompt, PromptTemplate)
            self.assertEqual(prompt.name, name)
            self.assertTrue(prompt.description.strip())
            self.assertGreater(len(prompt.required_inputs), 0)
            self.assertTrue(prompt.template.strip())

    def test_required_inputs_match_template_placeholders(self) -> None:
        # Every {placeholder} in the template must be in required_inputs
        # (and vice versa — no unused requirements). Catches prompt drift.
        import string

        formatter = string.Formatter()
        for name, prompt in ALL_PROMPTS.items():
            placeholders = {
                field
                for _, field, _, _ in formatter.parse(prompt.template)
                if field is not None and not field.isdigit()
            }
            self.assertEqual(
                placeholders,
                set(prompt.required_inputs),
                f"prompt {name!r}: placeholders ↔ required_inputs mismatch.\n"
                f"  in template only: {placeholders - set(prompt.required_inputs)}\n"
                f"  in required only: {set(prompt.required_inputs) - placeholders}",
            )

    def test_render_with_required_inputs_succeeds(self) -> None:
        # Smoke: every prompt renders given a stub of its required inputs
        for prompt in ALL_PROMPTS.values():
            inputs = {k: f"<{k}>" for k in prompt.required_inputs}
            out = prompt.render(**inputs)
            self.assertGreater(len(out), 0)

    def test_render_missing_input_raises_keyerror(self) -> None:
        prompt = get_prompt("threat_model_bootstrap")
        with self.assertRaises(KeyError):
            prompt.render(app_name="x")  # missing other required fields


class TestRealCodebaseConformance(unittest.TestCase):
    """Cross-check that real artifacts in apps/ conform to the abstractions
    used by the pipeline. Catches drift between real-world probe authoring
    practice and our scaffolder/catalogue."""

    def test_ha_probe_anti_patterns_in_catalogue(self) -> None:
        from probe_gen.pipeline.probes import ANTI_PATTERN_CATALOGUE

        repo_root = Path(__file__).resolve().parents[2]
        probe_path = (
            repo_root
            / "apps"
            / "home-assistant-android"
            / "checks"
            / "check_no_new_admin_refresh_tokens.py"
        )
        if not probe_path.is_file():
            self.skipTest("HA canonical probe not present in this checkout")
        src = probe_path.read_text(encoding="utf-8")
        import re as _re

        block = _re.search(
            r"Anti-pattern declarations:\n(.+?)(?:\n\nCitations:|\n\"\"\")",
            src,
            _re.DOTALL,
        )
        self.assertIsNotNone(block, "anti-pattern block missing in real probe")
        keys = _re.findall(
            r"^\s*\d+\.\s+([\w-]+):", block.group(1), _re.MULTILINE  # type: ignore[union-attr]
        )
        self.assertGreater(len(keys), 0, "no anti-patterns parsed from real probe")
        unknown = [k for k in keys if k not in ANTI_PATTERN_CATALOGUE]
        self.assertEqual(
            unknown,
            [],
            f"real HA probe declares anti-patterns not in our catalogue: "
            f"{unknown}. Update probe_gen/pipeline/probes.py:ANTI_PATTERN_CATALOGUE.",
        )


if __name__ == "__main__":
    unittest.main()
