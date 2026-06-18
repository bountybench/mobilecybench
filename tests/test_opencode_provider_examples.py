"""Pin tests for documentation/opencode_provider_examples/*.json.

These configs are copy-pasted by operators into ``OPENCODE_CONFIG_CONTENT``.
The fields covered here are easy to "fix" the wrong way; pin them so the
docs stay correct.
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


def test_together_glm52_interleaved_field_is_schema_accepted():
    # opencode's interleaved.field schema (Schema.Literals(["reasoning_content",
    # "reasoning_details"])) rejects any other value at config-load time and
    # exits 1 in <3s. Pin to "reasoning_content" so opencode actually starts.
    #
    # The field is used by opencode to PUT prior assistant reasoning back into
    # outbound requests as providerOptions.openaiCompatible.<field>; it is NOT
    # used to extract reasoning from incoming responses. Extraction happens in
    # @ai-sdk/openai-compatible via the hard-coded fallback
    # ``delta.reasoning_content ?? delta.reasoning`` — so Together (which
    # returns ``reasoning``) and Z.AI native (which returns ``reasoning_content``)
    # are both handled regardless of this field's value.
    cfg = _load("together_glm52.json")
    model = cfg["provider"]["togetherai"]["models"]["zai-org/GLM-5.2"]
    assert model["interleaved"] == {"field": "reasoning_content"}
    assert model["reasoning"] is True
