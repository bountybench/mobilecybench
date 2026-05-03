"""Decoy generator tests.

Mocks the LLM call so the suite is offline by default.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from probe_gen.pipeline.decoys import (
    ALL_DECOY_CLASSES,
    DecoyAttempt,
    DecoyBatch,
    by_class,
    claimed_successful,
    generate_decoys,
    render_decoy_md,
)


def _fake_llm_response(attempts: list[dict]) -> tuple[list, object]:
    from probe_gen.pipeline.llm import LLMResponse

    return (
        attempts,
        LLMResponse(
            text="<mocked>",
            model="gpt-5.5",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.0001,
        ),
    )


class TestDataclasses(unittest.TestCase):
    def test_decoy_attempt_construction(self) -> None:
        a = DecoyAttempt(
            decoy_class="artifact_forgery",
            description="d",
            command_or_payload="echo hi",
            expected_observation_after_decoy="o",
            would_satisfy_probe=True,
            rationale="r",
            model_family="claude",
        )
        self.assertEqual(a.decoy_class, "artifact_forgery")
        self.assertTrue(a.would_satisfy_probe)

    def test_batch_to_dict_round_trips_via_json(self) -> None:
        import json

        batch = DecoyBatch(
            probe_id="check_x",
            invariant_id="RA-C",
            attempts=[
                DecoyAttempt(
                    decoy_class="artifact_forgery",
                    description="d",
                    command_or_payload="echo hi",
                    expected_observation_after_decoy="o",
                    would_satisfy_probe=True,
                    rationale="r",
                    model_family="claude",
                )
            ],
            cost_usd=0.0123,
            input_tokens=100,
            output_tokens=50,
        )
        d = batch.to_dict()
        json.dumps(d)
        self.assertEqual(d["probe_id"], "check_x")
        self.assertEqual(len(d["attempts"]), 1)
        self.assertEqual(d["attempts"][0]["model_family"], "claude")


class TestHelpers(unittest.TestCase):
    def _attempt(self, cls, success):
        return DecoyAttempt(
            decoy_class=cls,
            description="d",
            command_or_payload="cmd",
            expected_observation_after_decoy="obs",
            would_satisfy_probe=success,
            rationale="r",
            model_family="openai",
        )

    def test_claimed_successful_filters(self) -> None:
        batch = DecoyBatch(
            probe_id="check_x",
            invariant_id="RA-C",
            attempts=[
                self._attempt("artifact_forgery", True),
                self._attempt("state_mimicry", False),
                self._attempt("api_short_circuit", True),
            ],
        )
        succ = claimed_successful(batch)
        self.assertEqual(len(succ), 2)
        self.assertTrue(all(a.would_satisfy_probe for a in succ))

    def test_by_class_groups_correctly(self) -> None:
        batch = DecoyBatch(
            probe_id="check_x",
            invariant_id="RA-C",
            attempts=[
                self._attempt("artifact_forgery", True),
                self._attempt("artifact_forgery", False),
                self._attempt("state_mimicry", True),
            ],
        )
        grouped = by_class(batch)
        self.assertEqual(len(grouped["artifact_forgery"]), 2)
        self.assertEqual(len(grouped["state_mimicry"]), 1)
        self.assertEqual(len(grouped["log_line_injection"]), 0)
        # All five classes present even if empty
        self.assertEqual(
            set(grouped.keys()) | set(ALL_DECOY_CLASSES),
            set(ALL_DECOY_CLASSES) | set(grouped.keys()),
        )


class TestGenerateDecoysMocked(unittest.TestCase):
    """Stub complete_json to drive generate_decoys through its branches."""

    def test_picks_cross_family_model(self) -> None:
        # Synthesizer was Claude → decoy should be GPT or Gemini family.
        attempts_payload = [
            {
                "decoy_class": "artifact_forgery",
                "description": "d",
                "command_or_payload": "echo hi",
                "expected_observation_after_decoy": "o",
                "would_satisfy_probe": True,
                "rationale": "r",
            }
        ]

        with patch(
            "probe_gen.pipeline.decoys.complete_json",
            return_value=_fake_llm_response(attempts_payload),
        ):
            batch = generate_decoys(
                invariant_id="RA-C",
                invariant_statement="X shall not Y.",
                probe_id="check_x",
                probe_source="def f(): pass",
                classes=["artifact_forgery"],
                n_per_class=1,
                synthesizer_model="claude-opus-4-7",
            )
        self.assertEqual(len(batch.attempts), 1)
        self.assertNotEqual(batch.attempts[0].model_family, "claude")
        self.assertGreater(batch.cost_usd, 0.0)

    def test_failure_is_recorded_not_raised(self) -> None:
        with patch(
            "probe_gen.pipeline.decoys.complete_json",
            side_effect=ValueError("simulated parse error"),
        ):
            batch = generate_decoys(
                invariant_id="RA-C",
                invariant_statement="X shall not Y.",
                probe_id="check_x",
                probe_source="def f(): pass",
                classes=["artifact_forgery"],
                n_per_class=2,
                synthesizer_model="claude-opus-4-7",
            )
        # One per requested class, marked as generation failure
        self.assertEqual(len(batch.attempts), 1)
        self.assertIn("generation failed", batch.attempts[0].description)
        self.assertFalse(batch.attempts[0].would_satisfy_probe)

    def test_each_class_yields_a_call(self) -> None:
        attempts_payload = [
            {
                "decoy_class": "artifact_forgery",
                "description": "d",
                "command_or_payload": "cmd",
                "expected_observation_after_decoy": "o",
                "would_satisfy_probe": False,
                "rationale": "r",
            }
        ]
        with patch(
            "probe_gen.pipeline.decoys.complete_json",
            return_value=_fake_llm_response(attempts_payload),
        ) as mock_complete:
            generate_decoys(
                invariant_id="RA-C",
                invariant_statement="X shall not Y.",
                probe_id="check_x",
                probe_source="def f(): pass",
                classes=list(ALL_DECOY_CLASSES),
                n_per_class=1,
                synthesizer_model="claude-opus-4-7",
            )
        self.assertEqual(mock_complete.call_count, len(ALL_DECOY_CLASSES))


class TestRender(unittest.TestCase):
    def test_render_decoy_md(self) -> None:
        batch = DecoyBatch(
            probe_id="check_x",
            invariant_id="RA-C",
            attempts=[
                DecoyAttempt(
                    decoy_class="artifact_forgery",
                    description="forge a token row",
                    command_or_payload="curl ...",
                    expected_observation_after_decoy="row exists",
                    would_satisfy_probe=True,
                    rationale="probe checks for row",
                    model_family="openai",
                )
            ],
            cost_usd=0.05,
        )
        md = render_decoy_md(batch)
        self.assertIn("check_x", md)
        self.assertIn("RA-C", md)
        self.assertIn("artifact_forgery", md)
        self.assertIn("SUCCESSFUL?", md)
        self.assertIn("forge a token row", md)


if __name__ == "__main__":
    unittest.main()
