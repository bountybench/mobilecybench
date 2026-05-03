"""Tests for the LLM client module.

Pure-helper tests run unconditionally. Live API calls are gated on the
``PROBE_GEN_LIVE_LLM=1`` env var so the suite stays fast and offline by
default.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from probe_gen.pipeline.llm import (
    DefaultModels,
    LLMResponse,
    cross_family_pick,
    extract_json,
    family_of,
)


class TestExtractJson(unittest.TestCase):
    def test_plain_object(self) -> None:
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})

    def test_plain_array(self) -> None:
        self.assertEqual(extract_json("[1,2,3]"), [1, 2, 3])

    def test_fenced_json(self) -> None:
        self.assertEqual(
            extract_json('here:\n```json\n{"x": 1}\n```\nbye'),
            {"x": 1},
        )

    def test_fenced_no_label(self) -> None:
        self.assertEqual(
            extract_json("```\n[1, 2]\n```"),
            [1, 2],
        )

    def test_prose_wrapped_object(self) -> None:
        self.assertEqual(
            extract_json('Here you go: {"key": "value"} all set.'),
            {"key": "value"},
        )

    def test_prose_wrapped_array(self) -> None:
        self.assertEqual(
            extract_json("Sure thing: [1, 2, 3] hope that helps"),
            [1, 2, 3],
        )

    def test_nested_object_balanced(self) -> None:
        self.assertEqual(
            extract_json('Result: {"a": {"b": [1, 2]}, "c": 3} ok'),
            {"a": {"b": [1, 2]}, "c": 3},
        )

    def test_string_with_braces_inside(self) -> None:
        # Brace-balancing must respect string literals
        self.assertEqual(
            extract_json('{"msg": "hi {there}", "n": 1}'),
            {"msg": "hi {there}", "n": 1},
        )

    def test_no_json_raises(self) -> None:
        with self.assertRaises(ValueError):
            extract_json("just prose, no JSON")

    def test_invalid_json_raises(self) -> None:
        with self.assertRaises(ValueError):
            extract_json("{bad: not quoted}")


class TestFamilyClassification(unittest.TestCase):
    def test_claude_family(self) -> None:
        self.assertEqual(family_of("claude-opus-4-7"), "claude")
        self.assertEqual(family_of("anthropic/claude-3"), "claude")

    def test_openai_family(self) -> None:
        self.assertEqual(family_of("gpt-5.5"), "openai")
        self.assertEqual(family_of("openai/gpt-4"), "openai")

    def test_gemini_family(self) -> None:
        self.assertEqual(family_of("gemini-3.1-pro"), "gemini")
        self.assertEqual(family_of("gemini/gemini-2.5-flash"), "gemini")

    def test_unknown(self) -> None:
        self.assertEqual(family_of("mistral-large"), "unknown")


class TestCrossFamilyPick(unittest.TestCase):
    def test_picks_different_family(self) -> None:
        # If excluded model is Claude, picked model should be GPT or Gemini
        self.assertNotEqual(family_of(cross_family_pick("claude-opus-4-7")), "claude")
        self.assertNotEqual(family_of(cross_family_pick("gpt-5.5")), "openai")
        self.assertNotEqual(family_of(cross_family_pick("gemini-3.1-pro")), "gemini")


class TestDefaults(unittest.TestCase):
    def test_default_model_constants_set(self) -> None:
        self.assertTrue(DefaultModels.INVARIANT_DERIVATION)
        self.assertTrue(DefaultModels.PATCH_SYNTHESIS)
        self.assertTrue(DefaultModels.ADVERSARIAL_DECOY)


class TestCompleteMocked(unittest.TestCase):
    """Simulate a litellm response without hitting the wire."""

    def test_complete_returns_llm_response(self) -> None:
        from probe_gen.pipeline import llm as llm_mod

        fake = {
            "choices": [{"message": {"content": "hello world"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }
        # MagicMock supports attribute and dict access
        fake_response = MagicMock()
        fake_response.__getitem__.side_effect = fake.__getitem__
        fake_response.get.side_effect = fake.get

        with patch.dict("sys.modules", {"litellm": MagicMock()}):
            import sys as _sys

            litellm_mock = _sys.modules["litellm"]
            litellm_mock.completion = MagicMock(return_value=fake_response)
            litellm_mock.completion_cost = MagicMock(return_value=0.0001)
            # Bypass env load
            llm_mod._ENV_LOADED = True
            response = llm_mod.complete(
                "test prompt", model="claude-haiku-4-5", max_tokens=10
            )
            self.assertIsInstance(response, LLMResponse)
            self.assertEqual(response.text, "hello world")
            self.assertEqual(response.model, "claude-haiku-4-5")
            self.assertEqual(response.input_tokens, 5)
            self.assertEqual(response.output_tokens, 3)
            self.assertGreater(response.cost_usd, 0.0)


@unittest.skipUnless(
    os.environ.get("PROBE_GEN_LIVE_LLM") == "1",
    "live LLM tests require PROBE_GEN_LIVE_LLM=1 env var",
)
class TestLiveLLM(unittest.TestCase):
    """Live API integration smoke tests. Skipped by default."""

    def test_claude_completion_live(self) -> None:
        from probe_gen.pipeline.llm import complete

        resp = complete(
            "Reply with exactly the word: pong", model="claude-haiku-4-5", max_tokens=20
        )
        self.assertIn("pong", resp.text.lower())
        self.assertGreater(resp.input_tokens, 0)


if __name__ == "__main__":
    unittest.main()
