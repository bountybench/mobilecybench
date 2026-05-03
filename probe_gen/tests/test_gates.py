"""Gate-runner unit tests.

Uses a temp directory + a tiny synthetic probe script (one that emits a
controlled ``score``) to exercise every branch of the gate semantics
without touching docker, the emulator, or the agent harness.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from probe_gen.pipeline.gates import (
    GateContext,
    StandardGateRunner,
    _parse_score,
    run_probe,
)
from probe_gen.pipeline.models import Probe

# A minimal probe template. Two parameters:
#   - score: 0 (fired / violated), 1 (not fired / clean), or "missing"
#   - sleep: seconds to sleep before emitting (for timeout tests)
PROBE_TEMPLATE = """\
import json, time, sys
time.sleep({sleep})
print("[INFO] probe diagnostic line", file=sys.stderr)
print(json.dumps({result}))
"""


def _write_probe(
    workdir: Path,
    probe_id: str,
    *,
    attacker_model: str = "remote_attacker",
    score: Optional[int] = 1,
    sleep: float = 0.0,
) -> Probe:
    """Write a fake probe script under the layout the gate runner resolves."""
    if attacker_model == "malicious_app":
        probe_dir = workdir / "checks"
    else:
        probe_dir = workdir / "remote_attacker" / "checks"
    probe_dir.mkdir(parents=True, exist_ok=True)
    script = probe_dir / f"{probe_id}.py"
    if score is None:
        result = '{"name": "no_score"}'
    else:
        result = f'{{"name": "fake", "score": {score}}}'
    script.write_text(
        PROBE_TEMPLATE.format(sleep=sleep, result=result), encoding="utf-8"
    )
    return Probe(
        probe_id=probe_id,
        invariant_id="TEST-1",
        channel="fake-channel",
        attacker_model=attacker_model,  # type: ignore[arg-type]
        category="access",
    )


class TestParseScore(unittest.TestCase):
    def test_picks_last_json_with_score(self) -> None:
        stdout = (
            "noise line\n"
            '{"name": "first", "score": 1}\n'
            "something else\n"
            '{"name": "last", "score": 0}\n'
        )
        self.assertEqual(_parse_score(stdout), 0)

    def test_returns_none_when_absent(self) -> None:
        self.assertIsNone(_parse_score("no json at all\nstill no json"))
        self.assertIsNone(_parse_score('{"name": "x"}'))  # no score field

    def test_handles_unparseable_lines(self) -> None:
        stdout = '{not json}\n{"score": 1}\n'
        self.assertEqual(_parse_score(stdout), 1)


class TestRunProbe(unittest.TestCase):
    def test_passing_probe_returns_score_1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            probe = _write_probe(app_dir, "check_pass", score=1)
            ctx = GateContext(repo_root=app_dir, app_dir=app_dir, run_dir=app_dir)
            outcome = run_probe(probe, ctx)
            self.assertEqual(outcome.return_code, 0)
            self.assertEqual(outcome.score, 1)
            self.assertFalse(outcome.fired)

    def test_failing_probe_returns_score_0(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            probe = _write_probe(app_dir, "check_fired", score=0)
            ctx = GateContext(repo_root=app_dir, app_dir=app_dir, run_dir=app_dir)
            outcome = run_probe(probe, ctx)
            self.assertEqual(outcome.score, 0)
            self.assertTrue(outcome.fired)

    def test_missing_probe_returns_rc_minus_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            probe = Probe(
                probe_id="check_does_not_exist",
                invariant_id="TEST-1",
                channel="x",
                attacker_model="remote_attacker",
                category="access",
            )
            ctx = GateContext(repo_root=app_dir, app_dir=app_dir, run_dir=app_dir)
            outcome = run_probe(probe, ctx)
            self.assertEqual(outcome.return_code, -1)
            self.assertIsNone(outcome.score)
            self.assertIn("not found", outcome.stderr)

    def test_unparseable_probe_score_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            probe = _write_probe(app_dir, "check_no_score", score=None)
            ctx = GateContext(repo_root=app_dir, app_dir=app_dir, run_dir=app_dir)
            outcome = run_probe(probe, ctx)
            self.assertEqual(outcome.return_code, 0)
            self.assertIsNone(outcome.score)
            self.assertFalse(outcome.fired)

    def test_timeout_returns_rc_minus_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            probe = _write_probe(app_dir, "check_slow", score=1, sleep=2.0)
            ctx = GateContext(repo_root=app_dir, app_dir=app_dir, run_dir=app_dir)
            outcome = run_probe(probe, ctx, timeout=1)
            self.assertEqual(outcome.return_code, -1)
            self.assertIn("timed out", outcome.stderr)


class TestStandardGateRunner(unittest.TestCase):
    def _ctx(self, app_dir: Path) -> GateContext:
        return GateContext(
            repo_root=app_dir,
            app_dir=app_dir,
            run_dir=app_dir,
            env=dict(os.environ),
        )

    def test_clean_baseline_pass_when_no_probe_fires(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            p1 = _write_probe(app_dir, "check_one", score=1)
            p2 = _write_probe(app_dir, "check_two", score=1)
            runner = StandardGateRunner()
            results = runner.run("clean_baseline", [p1, p2], self._ctx(app_dir))
            self.assertEqual(len(results), 2)
            self.assertTrue(all(r.outcome == "pass" for r in results))

    def test_clean_baseline_fail_when_probe_fires(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            p1 = _write_probe(app_dir, "check_clean", score=1)
            p2 = _write_probe(app_dir, "check_fired", score=0)
            runner = StandardGateRunner()
            results = runner.run("clean_baseline", [p1, p2], self._ctx(app_dir))
            outcomes = {r.artifact_id: r.outcome for r in results}
            self.assertEqual(outcomes["check_clean"], "pass")
            self.assertEqual(outcomes["check_fired"], "fail")

    def test_dual_comparator_vulnerable_pass_when_any_fires(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            p1 = _write_probe(app_dir, "check_one", score=1)  # didn't fire
            p2 = _write_probe(app_dir, "check_two", score=0)  # fired
            runner = StandardGateRunner()
            results = runner.run(
                "dual_comparator_vulnerable", [p1, p2], self._ctx(app_dir)
            )
            outcomes = {r.artifact_id: r.outcome for r in results}
            # The probe that fired counts as pass; others are skipped (some
            # other probe carried the signal).
            self.assertEqual(outcomes["check_two"], "pass")
            self.assertEqual(outcomes["check_one"], "skipped")

    def test_dual_comparator_vulnerable_fail_when_none_fires(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            p1 = _write_probe(app_dir, "check_a", score=1)
            p2 = _write_probe(app_dir, "check_b", score=1)
            runner = StandardGateRunner()
            results = runner.run(
                "dual_comparator_vulnerable", [p1, p2], self._ctx(app_dir)
            )
            self.assertTrue(all(r.outcome == "fail" for r in results))

    def test_setup_failure_marks_all_results_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            p1 = _write_probe(app_dir, "check_one", score=1)

            def boom(_ctx: GateContext) -> None:
                raise RuntimeError("emulator did not boot")

            runner = StandardGateRunner()
            results = runner.run("clean_baseline", [p1], self._ctx(app_dir), setup=boom)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].outcome, "error")
            self.assertIn("emulator did not boot", results[0].detail)

    def test_unknown_gate_marks_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            p1 = _write_probe(app_dir, "check_one", score=1)
            runner = StandardGateRunner()
            # Bypass type checker to test runtime behavior on bad input
            results = runner.run("not_a_real_gate", [p1], self._ctx(app_dir))  # type: ignore[arg-type]
            self.assertEqual(results[0].outcome, "error")
            self.assertIn("unknown gate", results[0].detail)

    def test_unparseable_probe_marks_error_in_clean_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            p1 = _write_probe(app_dir, "check_no_score", score=None)
            runner = StandardGateRunner()
            results = runner.run("clean_baseline", [p1], self._ctx(app_dir))
            self.assertEqual(results[0].outcome, "error")


class TestRunner(unittest.TestCase):
    """Integration test for the top-level runner against synthetic probes."""

    def test_run_gate_suite_persists_summary_and_records_results(self) -> None:
        from probe_gen.pipeline.models import Invariant
        from probe_gen.pipeline.runner import (
            make_clean_baseline_only_sequence,
            run_gate_suite,
        )

        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            run_dir = app_dir / "run"
            p1 = _write_probe(app_dir, "check_one", score=1)
            p2 = _write_probe(app_dir, "check_two", score=1)
            inv = Invariant(
                invariant_id="TEST-1",
                statement="Test invariant",
                attacker_model="remote_attacker",
            )
            ctx = GateContext(
                repo_root=app_dir,
                app_dir=app_dir,
                run_dir=run_dir,
                env=dict(os.environ),
            )
            run = run_gate_suite(
                app="testapp",
                invariants=[inv],
                probes=[p1, p2],
                gate_sequence=make_clean_baseline_only_sequence(),
                ctx=ctx,
            )
            self.assertEqual(len(run.gate_results), 2)
            self.assertTrue((run_dir / "summary.json").is_file())
            self.assertTrue((run_dir / "summary.md").is_file())
            md = (run_dir / "summary.md").read_text(encoding="utf-8")
            self.assertIn("clean_baseline", md)
            self.assertIn("check_one", md)
            self.assertIn("check_two", md)


if __name__ == "__main__":
    unittest.main()
