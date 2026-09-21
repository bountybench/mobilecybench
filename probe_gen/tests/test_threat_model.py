"""Threat-model parser tests.

Verifies parsing handles canonical and edge-case markdown layouts.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from probe_gen.pipeline.threat_model import (
    parse_threat_model,
    parse_threat_model_file,
    shall_nots_to_invariants,
)

CANONICAL = """
# title

other prose

## "Shall Not" threat model

### malicious_app

- MA-C: A foo shall not bar.
- MA-I: Another foo shall not baz.

### remote_attacker

- RA-C: A remote shall not whatnot.

## Next section

- not a shall-not.
"""

WRAPPED = """
## "Shall Not" threat model

### malicious_app

- MA-C: A long shall-not statement that
  wraps across multiple lines and continues
  on a third line.
- MA-I: Short single-line.
"""

NO_SECTION = """
# unrelated content
just text
"""


class TestParseThreatModel(unittest.TestCase):
    def test_canonical(self) -> None:
        sns = parse_threat_model(CANONICAL)
        ids = [sn.invariant_id for sn in sns]
        self.assertEqual(ids, ["MA-C", "MA-I", "RA-C"])
        models = {sn.invariant_id: sn.attacker_model for sn in sns}
        self.assertEqual(models["MA-C"], "malicious_app")
        self.assertEqual(models["MA-I"], "malicious_app")
        self.assertEqual(models["RA-C"], "remote_attacker")

    def test_stops_at_next_top_level_heading(self) -> None:
        sns = parse_threat_model(CANONICAL)
        ids = [sn.invariant_id for sn in sns]
        self.assertNotIn("not", ids)

    def test_no_section_returns_empty(self) -> None:
        self.assertEqual(parse_threat_model(NO_SECTION), [])

    def test_wrapped_bullet_is_joined(self) -> None:
        sns = parse_threat_model(WRAPPED)
        self.assertEqual(len(sns), 2)
        ma_c = next(sn for sn in sns if sn.invariant_id == "MA-C")
        # Wrapped lines joined with single spaces
        self.assertIn("wraps across", ma_c.statement)
        self.assertIn("third line", ma_c.statement)
        self.assertNotIn("\n", ma_c.statement)

    def test_invariant_anchor_format(self) -> None:
        sns = parse_threat_model(CANONICAL)
        invs = shall_nots_to_invariants(sns)
        ma_c = next(i for i in invs if i.invariant_id == "MA-C")
        self.assertEqual(ma_c.threat_model_anchor, "threat_model.md#shall-not-ma-c")


class TestRealHA(unittest.TestCase):
    def test_ha_threat_model_parses(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        path = repo_root / "apps" / "home-assistant-android" / "threat_model.md"
        if not path.is_file():
            self.skipTest("HA threat_model.md not present")
        sns = parse_threat_model_file(path)
        ids = [sn.invariant_id for sn in sns]
        # HA's threat_model.md has 4 MA-* and 4 RA-* shall-nots
        self.assertGreaterEqual(len(ids), 8)
        self.assertIn("MA-C", ids)
        self.assertIn("MA-X", ids)
        self.assertIn("RA-C", ids)
        self.assertIn("RA-X", ids)

    def test_ha_invariants_match_probe_invariant_ids(self) -> None:
        # Cross-check: every probe in HA's checks/ should reference an
        # invariant id that exists in HA's threat_model.md.
        from probe_gen.pipeline.discovery import discover_probes_in_app

        repo_root = Path(__file__).resolve().parents[2]
        ha_dir = repo_root / "apps" / "home-assistant-android"
        if not ha_dir.is_dir():
            self.skipTest("HA app not present")
        probes = discover_probes_in_app(ha_dir)
        sns = parse_threat_model_file(ha_dir / "threat_model.md")
        threat_model_ids = {sn.invariant_id for sn in sns}
        probe_ids = {p.invariant_id for p in probes if p.invariant_id != "UNKNOWN"}
        unknown = probe_ids - threat_model_ids
        self.assertEqual(
            unknown,
            set(),
            f"probes reference invariants not in threat_model.md: {unknown}",
        )


if __name__ == "__main__":
    unittest.main()
