"""Discovery-evaluator tests.

Probe discovery + header parsing + scoring against synthetic probes
written into a temp directory.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from probe_gen.pipeline.discovery import (
    DEFAULT_SEVERITY_WEIGHTS,
    DiscoveryReport,
    discover_probes_in_app,
    evaluate_discovery,
    load_invariants_severity_from_json,
    render_discovery_md,
)

# Sample probe with the canonical header. Used to validate header parsing.
PROBE_WITH_HEADER = '''"""Check: foo channel for {invariant_id}.

Shall-not enforced: {invariant_id} — "{statement}"
Channel: {channel}.
Attacker model: {attacker_model}.
Category: {category}.

Anti-pattern declarations:
  1. probe-runs-the-exploit: probe is read-only.
"""

import json
import sys
print(json.dumps({{"score": {score}}}))
'''


def _write_probe(
    workdir: Path,
    name: str,
    *,
    score: int = 1,
    invariant_id: str = "X-1",
    statement: str = "Test shall not.",
    channel: str = "test-channel",
    attacker_model: str = "remote_attacker",
    category: str = "access",
) -> Path:
    if attacker_model == "malicious_app":
        d = workdir / "checks"
    else:
        d = workdir / "remote_attacker" / "checks"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.py"
    p.write_text(
        PROBE_WITH_HEADER.format(
            invariant_id=invariant_id,
            statement=statement,
            channel=channel,
            attacker_model=attacker_model,
            category=category,
            score=score,
        ),
        encoding="utf-8",
    )
    return p


class TestProbeDiscovery(unittest.TestCase):
    def test_discovers_both_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            _write_probe(app_dir, "check_one", attacker_model="malicious_app")
            _write_probe(app_dir, "check_two", attacker_model="remote_attacker")
            probes = discover_probes_in_app(app_dir)
            self.assertEqual(len(probes), 2)
            models = {p.attacker_model for p in probes}
            self.assertEqual(models, {"malicious_app", "remote_attacker"})

    def test_filters_by_attacker_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            _write_probe(app_dir, "check_ma", attacker_model="malicious_app")
            _write_probe(app_dir, "check_ra", attacker_model="remote_attacker")
            ma_only = discover_probes_in_app(app_dir, attacker_models=["malicious_app"])
            self.assertEqual([p.probe_id for p in ma_only], ["check_ma"])

    def test_parses_header_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            _write_probe(
                app_dir,
                "check_x",
                invariant_id="MA-X",
                channel="ipc-broadcast",
                attacker_model="malicious_app",
                category="confidentiality",
            )
            probes = discover_probes_in_app(app_dir)
            self.assertEqual(len(probes), 1)
            p = probes[0]
            self.assertEqual(p.invariant_id, "MA-X")
            self.assertEqual(p.channel, "ipc-broadcast")
            self.assertEqual(p.attacker_model, "malicious_app")
            self.assertEqual(p.category, "confidentiality")

    def test_skips_non_check_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            _write_probe(app_dir, "check_ok")
            # Add an __init__.py and a non-check .py file
            (app_dir / "remote_attacker" / "checks" / "__init__.py").write_text("")
            (app_dir / "remote_attacker" / "checks" / "helper.py").write_text(
                "# not a probe\n"
            )
            probes = discover_probes_in_app(app_dir)
            self.assertEqual(len(probes), 1)


class TestDiscoveryEvaluation(unittest.TestCase):
    def test_no_probes_fired_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            _write_probe(app_dir, "check_clean1", score=1, invariant_id="A")
            _write_probe(app_dir, "check_clean2", score=1, invariant_id="B")
            report = evaluate_discovery(app_dir=app_dir, repo_root=app_dir)
            self.assertEqual(report.probes_run, 2)
            self.assertEqual(report.probes_fired, 0)
            self.assertEqual(report.probes_error, 0)
            self.assertEqual(report.invariants_violated, [])
            self.assertEqual(report.severity_weighted_score, 0.0)

    def test_one_probe_fired_default_medium(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            _write_probe(app_dir, "check_x", score=0, invariant_id="X")
            report = evaluate_discovery(app_dir=app_dir, repo_root=app_dir)
            self.assertEqual(report.probes_fired, 1)
            self.assertEqual(report.invariants_violated, ["X"])
            # Default severity is MEDIUM (4.0)
            self.assertEqual(
                report.severity_weighted_score, DEFAULT_SEVERITY_WEIGHTS["MEDIUM"]
            )

    def test_severity_lookup_applies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            _write_probe(app_dir, "check_x", score=0, invariant_id="X")
            _write_probe(app_dir, "check_y", score=0, invariant_id="Y")
            report = evaluate_discovery(
                app_dir=app_dir,
                repo_root=app_dir,
                invariants_severity={"X": "CRITICAL", "Y": "LOW"},
            )
            expected = (
                DEFAULT_SEVERITY_WEIGHTS["CRITICAL"] + DEFAULT_SEVERITY_WEIGHTS["LOW"]
            )
            self.assertEqual(report.severity_weighted_score, expected)

    def test_invariant_counted_once_even_if_two_probes_fire(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            _write_probe(app_dir, "check_a", score=0, invariant_id="X", channel="a")
            _write_probe(app_dir, "check_b", score=0, invariant_id="X", channel="b")
            report = evaluate_discovery(app_dir=app_dir, repo_root=app_dir)
            self.assertEqual(report.probes_fired, 2)
            self.assertEqual(report.invariants_violated, ["X"])  # deduped
            self.assertEqual(
                report.severity_weighted_score, DEFAULT_SEVERITY_WEIGHTS["MEDIUM"]
            )

    def test_to_dict_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            _write_probe(app_dir, "check_x", score=1, invariant_id="X")
            report = evaluate_discovery(app_dir=app_dir, repo_root=app_dir)
            d = report.to_dict()
            json.dumps(d)  # serializable
            self.assertEqual(d["app"], app_dir.name)


class TestSeverityLoader(unittest.TestCase):
    def test_load_simple_dict(self) -> None:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"X": "high", "Y": "Low"}, f)
            path = Path(f.name)
        try:
            self.assertEqual(
                load_invariants_severity_from_json(path), {"X": "HIGH", "Y": "LOW"}
            )
        finally:
            path.unlink()

    def test_load_invariant_array(self) -> None:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(
                [
                    {"invariant_id": "X", "cvss": {"severity": "HIGH"}},
                    {"invariant_id": "Y", "cvss": {"severity": "low"}},
                    {"invariant_id": "Z"},  # no cvss — skipped
                ],
                f,
            )
            path = Path(f.name)
        try:
            self.assertEqual(
                load_invariants_severity_from_json(path),
                {"X": "HIGH", "Y": "LOW"},
            )
        finally:
            path.unlink()


class TestRender(unittest.TestCase):
    def test_render_markdown_includes_key_fields(self) -> None:
        report = DiscoveryReport(
            app="testapp",
            probes_run=3,
            probes_fired=1,
            probes_error=0,
            invariants_violated=["X-1"],
            severity_weighted_score=4.0,
        )
        md = render_discovery_md(report)
        self.assertIn("Discovery report — testapp", md)
        self.assertIn("**3**", md)
        self.assertIn("X-1", md)
        self.assertIn("4.0", md)


class TestRealHA(unittest.TestCase):
    """Integration test: parse the canonical HA probe set."""

    def test_ha_probes_parse_with_invariant_ids(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        ha_dir = repo_root / "apps" / "home-assistant-android"
        if not ha_dir.is_dir():
            self.skipTest("HA app not present")
        probes = discover_probes_in_app(ha_dir)
        self.assertGreater(len(probes), 0)
        # Every probe should have a non-UNKNOWN invariant id
        unknown = [p for p in probes if p.invariant_id == "UNKNOWN"]
        self.assertEqual(
            unknown,
            [],
            f"probes failed to parse invariant_id: {[p.probe_id for p in unknown]}",
        )
        # Every probe should declare a non-trivial channel
        no_channel = [p for p in probes if p.channel == "unknown"]
        self.assertEqual(no_channel, [])


if __name__ == "__main__":
    # Make stderr quieter for the smoke runs (probes print [PASS]/[FAIL] there)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    unittest.main()
