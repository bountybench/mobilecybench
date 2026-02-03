import pytest

from utils.token_costs import (
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
        cache_input_tokens=500,
    )
    scale = 1_000_000.0
    expected_cost = (1500 / scale) * 5.0 + (1000 / scale) * 15.0 + (500 / scale) * 0.5
    assert cost == pytest.approx(expected_cost, rel=1e-9)


@pytest.mark.pricing
def test_strip_date_suffix():
    """Test date suffix stripping from model names."""
    # Test with date suffix
    assert _strip_date_suffix("gpt-5-2025-08-07") == "gpt-5"
    assert _strip_date_suffix("gpt-5-mini-2025-08-07") == "gpt-5-mini"
    assert _strip_date_suffix("gpt-5-nano-2025-08-07") == "gpt-5-nano"

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

    # Test unknown model with date suffix (should default to zeros)
    p = get_pricing_for_model(
        "unknown-model-2025-08-07", pricing_map=pricing_map, warn=False
    )
    assert p.input == 0.0 and p.output == 0.0 and p.cache_input == 0.0

    p = get_pricing_for_model("unknown-model", pricing_map=pricing_map, warn=False)
    assert p.input == 0.0 and p.output == 0.0 and p.cache_input == 0.0


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


class _UsageWithDetails(_Usage):
    """Mock usage object with input_tokens_details similar to OpenAI response."""

    def __init__(self, input_tokens, output_tokens, cached_tokens):
        super().__init__(input_tokens=input_tokens, output_tokens=output_tokens)
        self.input_tokens_details = _InputDetails(cached_tokens)


@pytest.mark.token_tracker
def test_tracker_record_known_model_no_cache_details():
    tracker = TokenTracker(jsonl_path="")  # Disable file output in tests
    mock_resp = _Resp(rid="r1", usage=_Usage(input_tokens=1000, output_tokens=500))
    rec = tracker.record_from_openai_response(mock_resp, model="gpt-4.1")

    assert rec.model == "gpt-4.1"
    assert rec.request_id == "r1"
    assert rec.input_tokens == 1000
    assert rec.output_tokens == 500
    assert rec.cache_input_tokens == 0
    assert rec.cost_usd > 0

    totals = tracker.totals()
    assert totals["calls"] == 1


@pytest.mark.token_tracker
def test_tracker_record_known_model_with_cache_details():
    tracker = TokenTracker(jsonl_path="")  # Disable file output in tests
    mock_resp = _Resp(rid="r2", usage=_UsageWithDetails(200, 100, 50))
    rec = tracker.record_from_openai_response(mock_resp, model="gpt-4.1")

    assert rec.model == "gpt-4.1"
    assert rec.request_id == "r2"
    assert rec.input_tokens == 200
    assert rec.output_tokens == 100
    assert rec.cache_input_tokens == 50


@pytest.mark.token_tracker
def test_tracker_unknown_model_cost_zero_with_warning():
    tracker = TokenTracker(jsonl_path="")  # Disable file output in tests
    mock_resp = _Resp(rid="r3", usage=_Usage(input_tokens=1000, output_tokens=1000))
    rec = tracker.record_from_openai_response(mock_resp, model="unknown-model")

    assert rec.cost_usd == 0.0  # unknown model yields zero with warning in logs


@pytest.mark.token_tracker
def test_tracker_multiple_records_accumulate_totals():
    """Simulate multiple calls and check aggregated totals.

    First call: 500 input, 200 output, no cache details
    Second call: 300 input, 100 output, 50 cached tokens

    """
    tracker = TokenTracker(jsonl_path="")  # Disable file output in tests
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
    assert totals["cache_input_tokens"] == 50

    excepted_cost = compute_cost_usd(
        pricing=get_pricing_for_model("gpt-4.1", tracker._pricing_map),
        input_tokens=800,
        output_tokens=300,
        cache_input_tokens=50,
    )
    assert totals["cost_usd"] == pytest.approx(excepted_cost, rel=1e-9)
    print(f"totals['cost_usd']: {totals['cost_usd']}")
