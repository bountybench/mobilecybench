import pytest

from agent.custom.model_providers.factory import SupportedModel
from utils.token_costs import (
    HighContextPricing,
    ModelPricing,
    _strip_date_suffix,
    compute_cost_usd,
    get_pricing_for_model,
    load_pricing,
)
from utils.token_tracker import TokenTracker


##########################################
#           Token Pricing Tests          #
##########################################
@pytest.mark.pricing
def test_unknown_model_warns_and_defaults_zero():
    """Unknown model should log a warning and return zero pricing."""
    pm = load_pricing()
    p = get_pricing_for_model("unknown-model", pricing_map=pm, warn=True)
    assert isinstance(p, ModelPricing)
    assert p.input == 0.0 and p.output == 0.0 and p.cache_input == 0.0


@pytest.mark.pricing
def test_compute_cost_without_cache():
    """Simple cost calculation without cache input tokens."""
    p = ModelPricing(input=5.0, output=15.0)
    cost = compute_cost_usd(p, input_tokens=1000, output_tokens=2000)
    scale = 1_000_000.0
    expected_cost = (1000 / scale) * 5.0 + (2000 / scale) * 15.0
    assert cost == pytest.approx(expected_cost, rel=1e-9)


@pytest.mark.pricing
def test_compute_cost_with_cache_read_only():
    """Cost calculation with cache read-only tokens.

    billed input = input - cache_input
    price calculated based on billed input, output, and cache input
    """
    p = ModelPricing(input=5.0, output=15.0, cache_input=0.5)
    cost = compute_cost_usd(
        p,
        input_tokens=2000,
        output_tokens=1000,
        cached_input_tokens=500,
    )
    scale = 1_000_000.0
    expected_cost = (1500 / scale) * 5.0 + (1000 / scale) * 15.0 + (500 / scale) * 0.5
    assert cost == pytest.approx(expected_cost, rel=1e-9)


@pytest.mark.pricing
def test_compute_cost_with_reasoning_tokens_uses_separate_rate_without_double_counting():
    """Reasoning tokens should be split out of output tokens, not double-counted."""
    p = ModelPricing(input=5.0, output=15.0, reasoning=7.5)
    cost = compute_cost_usd(
        p,
        input_tokens=2000,
        output_tokens=1000,
        reasoning_tokens=400,
    )
    scale = 1_000_000.0
    expected_cost = (2000 / scale) * 5.0 + (600 / scale) * 15.0 + (400 / scale) * 7.5
    assert cost == pytest.approx(expected_cost, rel=1e-9)


@pytest.mark.pricing
def test_compute_cost_with_reasoning_tokens_falls_back_to_high_context_output_rate():
    """Reasoning fallback should use the active tier's output rate, not the base tier."""
    p = ModelPricing(
        input=2.5,
        output=15.0,
        cache_input=0.25,
        high_context=HighContextPricing(
            input_threshold=272_000,
            input=5.0,
            output=22.5,
            cache_input=0.5,
        ),
    )
    cost = compute_cost_usd(
        p,
        input_tokens=300_000,
        output_tokens=1000,
        reasoning_tokens=400,
    )
    scale = 1_000_000.0
    expected_cost = (300_000 / scale) * 5.0 + (1000 / scale) * 22.5
    assert cost == pytest.approx(expected_cost, rel=1e-9)


@pytest.mark.pricing
def test_compute_cost_with_reasoning_tokens_exceeding_output_tokens_no_double_count():
    """If reasoning exceeds output (inconsistent data), text portion clamps to zero."""
    p = ModelPricing(input=5.0, output=15.0, reasoning=7.5)
    cost = compute_cost_usd(
        p,
        output_tokens=1000,
        reasoning_tokens=1200,
    )
    scale = 1_000_000.0
    # text = max(1000-1200, 0) = 0; all output billed as reasoning
    expected_cost = (1200 / scale) * 7.5
    assert cost == pytest.approx(expected_cost, rel=1e-9)


@pytest.mark.pricing
@pytest.mark.parametrize(
    "input_tokens, expected_input_rate, expected_output_rate",
    [
        (100_000, 2.5, 15.0),  # below threshold: standard rates
        (272_000, 2.5, 15.0),  # at threshold: standard rates (> triggers high tier)
        (300_000, 5.0, 22.5),  # above threshold: high-context rates
    ],
)
def test_high_context_tiered_pricing(
    input_tokens, expected_input_rate, expected_output_rate
):
    """High-context tier activates only when input_tokens exceeds the threshold."""
    pricing = ModelPricing(
        input=2.5,
        output=15.0,
        cache_input=0.25,
        high_context=HighContextPricing(
            input_threshold=272_000,
            input=5.0,
            output=22.5,
            cache_input=0.5,
        ),
    )
    output_tokens = 5_000
    cost = compute_cost_usd(
        pricing, input_tokens=input_tokens, output_tokens=output_tokens
    )
    per_million = 1_000_000.0
    expected = (input_tokens / per_million) * expected_input_rate + (
        output_tokens / per_million
    ) * expected_output_rate
    assert cost == pytest.approx(expected, rel=1e-9)


@pytest.mark.pricing
def test_strip_date_suffix():
    """Test date suffix stripping from model names."""
    # Test with date suffix
    assert _strip_date_suffix("gpt-5-2025-08-07") == "gpt-5"
    assert _strip_date_suffix("gpt-5-mini-2025-08-07") == "gpt-5-mini"
    assert _strip_date_suffix("gpt-5-nano-2025-08-07") == "gpt-5-nano"
    assert _strip_date_suffix("claude-sonnet-4-5-20250929") == "claude-sonnet-4-5"

    # Test without date suffix (should remain unchanged)
    assert _strip_date_suffix("gpt-5") == "gpt-5"
    assert _strip_date_suffix("gpt-4") == "gpt-4"

    # Test with partial date patterns (should not match, not a typical format)
    # OpenAI model naming patterns: https://github.com/openai/openai-python/blob/a52463c9/src/openai/types/shared_params/chat_model.py
    assert _strip_date_suffix("gpt-5-2025") == "gpt-5-2025"
    assert _strip_date_suffix("gpt-5-25-08-07") == "gpt-5-25-08-07"


@pytest.mark.pricing
def test_get_pricing_for_model_with_date_suffix():
    """Test model pricing lookup with date suffix fallback."""
    pricing_map = {
        "gpt-5": ModelPricing(input=1.25, output=10.0, cache_input=0.125),
        "gpt-5-mini": ModelPricing(input=0.25, output=2.0, cache_input=0.025),
        "claude-sonnet-4-5": ModelPricing(input=3.0, output=15.0, cache_input=0.3),
    }

    # Test exact match
    p = get_pricing_for_model("gpt-5", pricing_map=pricing_map, warn=False)
    assert p.input == 1.25 and p.output == 10.0 and p.cache_input == 0.125

    # Test date suffix fallback
    p = get_pricing_for_model("gpt-5-2025-08-07", pricing_map=pricing_map, warn=False)
    assert p.input == 1.25 and p.output == 10.0 and p.cache_input == 0.125

    p = get_pricing_for_model(
        "gpt-5-mini-2025-08-07", pricing_map=pricing_map, warn=False
    )
    assert p.input == 0.25 and p.output == 2.0 and p.cache_input == 0.025

    p = get_pricing_for_model(
        "claude-sonnet-4-5-20250929", pricing_map=pricing_map, warn=False
    )
    assert p.input == 3.0 and p.output == 15.0 and p.cache_input == 0.3

    # Test unknown model with date suffix (should default to zeros)
    p = get_pricing_for_model(
        "unknown-model-2025-08-07", pricing_map=pricing_map, warn=False
    )
    assert p.input == 0.0 and p.output == 0.0 and p.cache_input == 0.0

    p = get_pricing_for_model("unknown-model", pricing_map=pricing_map, warn=False)
    assert p.input == 0.0 and p.output == 0.0 and p.cache_input == 0.0


@pytest.mark.pricing
def test_get_pricing_for_model_with_provider_prefix():
    """Test model pricing lookup with provider prefix (LiteLLM format)."""
    pricing_map = {
        "gemini-2.0-flash": ModelPricing(input=0.1, output=0.4, cache_input=0.025),
        "gemini-3-pro-preview": ModelPricing(input=2.0, output=12.0, cache_input=0.2),
        "claude-3-opus": ModelPricing(input=15.0, output=75.0, cache_input=1.5),
    }

    # Test with gemini/ prefix
    p = get_pricing_for_model(
        "gemini/gemini-2.0-flash", pricing_map=pricing_map, warn=False
    )
    assert p.input == 0.1 and p.output == 0.4 and p.cache_input == 0.025

    p = get_pricing_for_model(
        "gemini/gemini-3-pro-preview", pricing_map=pricing_map, warn=False
    )
    assert p.input == 2.0 and p.output == 12.0 and p.cache_input == 0.2

    # Test with anthropic/ prefix
    p = get_pricing_for_model(
        "anthropic/claude-3-opus", pricing_map=pricing_map, warn=False
    )
    assert p.input == 15.0 and p.output == 75.0 and p.cache_input == 1.5

    # Test without prefix still works
    p = get_pricing_for_model("gemini-2.0-flash", pricing_map=pricing_map, warn=False)
    assert p.input == 0.1 and p.output == 0.4 and p.cache_input == 0.025

    # Test unknown model with prefix (should default to zeros)
    p = get_pricing_for_model(
        "gemini/unknown-model", pricing_map=pricing_map, warn=False
    )
    assert p.input == 0.0 and p.output == 0.0 and p.cache_input == 0.0


@pytest.mark.pricing
def test_supported_models_have_nonzero_pricing():
    """Every supported model should resolve to non-zero input/output pricing."""
    pricing_map = load_pricing()

    for model in SupportedModel:
        pricing = get_pricing_for_model(
            model.value.api_id, pricing_map=pricing_map, warn=False
        )
        assert pricing.input > 0.0, f"{model.value.api_id} missing input pricing"
        assert pricing.output > 0.0, f"{model.value.api_id} missing output pricing"


@pytest.mark.pricing
def test_claude_fable_5_pricing_matches_official_docs():
    pricing = get_pricing_for_model(
        "claude-fable-5", pricing_map=load_pricing(), warn=False
    )
    assert pricing.input == pytest.approx(10.0, rel=1e-9)
    assert pricing.cache_input == pytest.approx(1.0, rel=1e-9)
    assert pricing.cache_creation_5m == pytest.approx(12.5, rel=1e-9)
    assert pricing.cache_creation_1h == pytest.approx(20.0, rel=1e-9)
    assert pricing.output == pytest.approx(50.0, rel=1e-9)


@pytest.mark.pricing
def test_claude_opus_4_8_pricing_matches_official_docs():
    pricing = get_pricing_for_model(
        "claude-opus-4-8", pricing_map=load_pricing(), warn=False
    )
    assert pricing.input == pytest.approx(5.0, rel=1e-9)
    assert pricing.cache_input == pytest.approx(0.5, rel=1e-9)
    assert pricing.cache_creation_5m == pytest.approx(6.25, rel=1e-9)
    assert pricing.cache_creation_1h == pytest.approx(10.0, rel=1e-9)
    assert pricing.output == pytest.approx(25.0, rel=1e-9)


@pytest.mark.pricing
def test_o4_mini_cached_input_pricing_matches_official_docs():
    pricing = get_pricing_for_model("o4-mini", pricing_map=load_pricing(), warn=False)
    assert pricing.input == pytest.approx(1.1, rel=1e-9)
    assert pricing.cache_input == pytest.approx(0.275, rel=1e-9)
    assert pricing.output == pytest.approx(4.4, rel=1e-9)


@pytest.mark.pricing
def test_together_glm52_pricing_matches_together_docs():
    pricing = get_pricing_for_model(
        "togetherai/zai-org/GLM-5.2", pricing_map=load_pricing(), warn=False
    )
    assert pricing.input == pytest.approx(1.4, rel=1e-9)
    assert pricing.cache_input == pytest.approx(0.26, rel=1e-9)
    assert pricing.output == pytest.approx(4.4, rel=1e-9)


##########################################
#          Token Tracker Tests           #
##########################################
class _Usage:
    """Mock usage object similar to OpenAI response."""

    def __init__(self, input_tokens=0, output_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _Resp:
    """Mock response object similar to OpenAI response."""

    def __init__(self, rid: str, usage: _Usage):
        self.id = rid
        self.usage = usage


class _InputDetails:
    def __init__(self, cached_tokens: int):
        self.cached_tokens = cached_tokens


class _OutputDetails:
    def __init__(self, reasoning_tokens: int):
        self.reasoning_tokens = reasoning_tokens


class _UsageWithDetails(_Usage):
    """Mock usage object with input_tokens_details similar to OpenAI response."""

    def __init__(self, input_tokens, output_tokens, cached_tokens):
        super().__init__(input_tokens=input_tokens, output_tokens=output_tokens)
        self.input_tokens_details = _InputDetails(cached_tokens)


class _UsageWithReasoningDetails(_UsageWithDetails):
    """Mock usage object with cache and reasoning details."""

    def __init__(self, input_tokens, output_tokens, cached_tokens, reasoning_tokens):
        super().__init__(input_tokens, output_tokens, cached_tokens)
        self.output_tokens_details = _OutputDetails(reasoning_tokens)


class _ChatCompletionUsageWithReasoning:
    """Mock usage object similar to LiteLLM / Chat Completions format."""

    def __init__(
        self, prompt_tokens, completion_tokens, cached_tokens, reasoning_tokens
    ):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.prompt_tokens_details = _InputDetails(cached_tokens)
        self.completion_tokens_details = _OutputDetails(reasoning_tokens)


@pytest.mark.token_tracker
def test_tracker_record_known_model_no_cache_details():
    tracker = TokenTracker(jsonl_path="token_test.jsonl")
    mock_resp = _Resp(rid="r1", usage=_Usage(input_tokens=1000, output_tokens=500))
    rec = tracker.record_from_openai_response(mock_resp, model="gpt-4.1")

    assert rec.model == "gpt-4.1"
    assert rec.request_id == "r1"
    assert rec.input_tokens == 1000
    assert rec.output_tokens == 500
    assert rec.reasoning_tokens == 0
    assert rec.cached_input_tokens == 0
    assert rec.cost_usd > 0

    totals = tracker.totals()
    assert totals["calls"] == 1


@pytest.mark.token_tracker
def test_custom_agent_result_token_totals_omits_calls_and_cost():
    """Custom agent strips `cost_usd` (top-level field) and `calls`
    (lives in metrics.timing.llm_call_count) from token_totals before
    shipping them to result.json. Mirrors agent/custom/agent.py."""
    tracker = TokenTracker(jsonl_path="token_test.jsonl")
    tracker.record_from_openai_response(
        _Resp(rid="r1", usage=_Usage(input_tokens=1000, output_tokens=500)),
        model="gpt-4.1",
    )

    totals = tracker.totals()
    totals.pop("cost_usd", None)
    totals.pop("calls", None)

    assert "calls" not in totals
    assert "cost_usd" not in totals
    assert totals["input_tokens"] == 1000
    assert totals["output_tokens"] == 500


@pytest.mark.token_tracker
def test_tracker_record_known_model_with_cache_details():
    tracker = TokenTracker(jsonl_path="token_test.jsonl")
    mock_resp = _Resp(rid="r2", usage=_UsageWithDetails(200, 100, 50))
    rec = tracker.record_from_openai_response(mock_resp, model="gpt-4.1")

    assert rec.model == "gpt-4.1"
    assert rec.request_id == "r2"
    assert rec.input_tokens == 200
    assert rec.output_tokens == 100
    assert rec.reasoning_tokens == 0
    assert rec.cached_input_tokens == 50


@pytest.mark.token_tracker
@pytest.mark.parametrize("model", ["gpt-5.2-pro", "gpt-5.2-codex"])
def test_tracker_supported_openai_models_compute_nonzero_cost(model):
    tracker = TokenTracker(jsonl_path="token_test.jsonl")
    mock_resp = _Resp(
        rid=f"{model}-resp", usage=_Usage(input_tokens=200, output_tokens=100)
    )
    rec = tracker.record_from_openai_response(mock_resp, model=model)

    assert rec.input_tokens == 200
    assert rec.output_tokens == 100
    assert rec.cost_usd > 0.0


@pytest.mark.token_tracker
def test_tracker_record_known_model_with_reasoning_details():
    tracker = TokenTracker(jsonl_path="token_test.jsonl")
    mock_resp = _Resp(rid="r2b", usage=_UsageWithReasoningDetails(200, 100, 50, 40))
    rec = tracker.record_from_openai_response(mock_resp, model="o3")

    assert rec.model == "o3"
    assert rec.request_id == "r2b"
    assert rec.input_tokens == 200
    assert rec.output_tokens == 100
    assert rec.reasoning_tokens == 40
    assert rec.cached_input_tokens == 50

    totals = tracker.totals()
    assert totals["reasoning_tokens"] == 40


@pytest.mark.token_tracker
def test_tracker_extracts_chat_completions_style_reasoning_details():
    tracker = TokenTracker(jsonl_path="token_test.jsonl")
    mock_resp = _Resp(
        rid="r2c",
        usage=_ChatCompletionUsageWithReasoning(200, 100, 50, 40),
    )
    rec = tracker.record_from_openai_response(mock_resp, model="o3")

    assert rec.input_tokens == 200
    assert rec.output_tokens == 100
    assert rec.reasoning_tokens == 40
    assert rec.cached_input_tokens == 50


@pytest.mark.token_tracker
def test_tracker_extracts_top_level_reasoning_tokens_from_dict_usage():
    tracker = TokenTracker(jsonl_path="token_test.jsonl")
    mock_resp = {
        "id": "r2d",
        "usage": {
            "prompt_tokens": 200,
            "completion_tokens": 100,
            "reasoning_tokens": 40,
        },
    }
    rec = tracker.record_from_openai_response(mock_resp, model="o3")

    assert rec.input_tokens == 200
    assert rec.output_tokens == 100
    assert rec.reasoning_tokens == 40
    assert rec.cached_input_tokens == 0


@pytest.mark.token_tracker
def test_tracker_unknown_model_cost_zero_with_warning():
    tracker = TokenTracker(jsonl_path="token_test.jsonl")
    mock_resp = _Resp(rid="r3", usage=_Usage(input_tokens=1000, output_tokens=1000))
    rec = tracker.record_from_openai_response(mock_resp, model="unknown-model")

    assert rec.reasoning_tokens == 0
    assert rec.cost_usd == 0.0  # unknown model yields zero with warning in logs


@pytest.mark.token_tracker
def test_tracker_multiple_records_accumulate_totals():
    """Simulate multiple calls and check aggregated totals.

    First call: 500 input, 200 output, no cache details
    Second call: 300 input, 100 output, 50 cached tokens

    """
    tracker = TokenTracker(jsonl_path="token_test.jsonl")
    resp1 = _Resp(rid="r1", usage=_Usage(input_tokens=500, output_tokens=200))
    tracker.record_from_openai_response(resp1, model="gpt-4.1")

    resp2 = _Resp(
        rid="r2",
        usage=_UsageWithDetails(input_tokens=300, output_tokens=100, cached_tokens=50),
    )
    tracker.record_from_openai_response(resp2, model="gpt-4.1")

    totals = tracker.totals()
    assert totals["calls"] == 2
    assert totals["input_tokens"] == 800
    assert totals["output_tokens"] == 300
    assert totals["reasoning_tokens"] == 0
    assert totals["cached_input_tokens"] == 50

    excepted_cost = compute_cost_usd(
        pricing=get_pricing_for_model("gpt-4.1", tracker._pricing_map),
        input_tokens=800,
        output_tokens=300,
        cached_input_tokens=50,
        reasoning_tokens=0,
    )
    assert totals["cost_usd"] == pytest.approx(excepted_cost, rel=1e-9)
    print(f"totals['cost_usd']: {totals['cost_usd']}")
