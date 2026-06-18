"""Pin tests for documentation/opencode_provider_examples/*.json.

These configs are copy-pasted by operators into ``OPENCODE_CONFIG_CONTENT``.
The fields covered here are easy to "fix" the wrong way (e.g. Together's
response uses ``reasoning``, while Z.AI's native API uses
``reasoning_content`` — the two providers look similar enough that swapping
them is silent and only shows up as missing reasoning text in
``conversation.jsonl``). Pin the values so the docs stay correct.
"""

import json
import pathlib

EXAMPLES_DIR = (
    pathlib.Path(__file__).resolve().parent.parent
    / "documentation"
    / "opencode_provider_examples"
)


def _load(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text())


def test_together_glm52_interleaved_field_is_reasoning():
    # Together's OpenAI-compatible response surfaces reasoning text on the
    # ``reasoning`` JSON field (verified via /v1/chat/completions). Z.AI's
    # native API uses ``reasoning_content`` — do not confuse them.
    cfg = _load("together_glm52.json")
    model = cfg["provider"]["togetherai"]["models"]["zai-org/GLM-5.2"]
    assert model["interleaved"] == {"field": "reasoning"}
    assert model["reasoning"] is True
