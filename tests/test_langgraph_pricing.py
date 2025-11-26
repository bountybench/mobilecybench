"""Tests for LangGraph pricing tracker.

Run with: pytest tests/test_langgraph_pricing.py -v
"""

import json
from unittest.mock import Mock

import pytest

from agent.multi.langgraph_pricing_tracker import (
    LangGraphCallbackHandler,
    LangGraphPricingTracker,
)


@pytest.fixture
def tracker():
    """Create a tracker with default pricing."""
    return LangGraphPricingTracker()


@pytest.fixture
def mock_llm_result():
    """Create a mock LLMResult with usage data."""
    result = Mock()
    result.generations = [Mock()]
    result.llm_output = {
        "model_name": "gpt-5",
        "token_usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "prompt_tokens_details": {"cached_tokens": 200},
        },
    }
    return result


def test_record_call_basic(tracker):
    """Test basic call recording."""
    record = tracker.record_call(
        model="gpt-5",
        role="auxiliary",
        worker_id=None,
        input_tokens=1000,
        output_tokens=500,
        cache_input_tokens=0,
    )

    assert record.model == "gpt-5"
    assert record.role == "auxiliary"
    assert record.worker_id is None
    assert record.input_tokens == 1000
    assert record.output_tokens == 500
    assert record.cache_input_tokens == 0
    assert record.cost_usd > 0  # Should have computed cost

    # Check that record was stored
    assert len(tracker._records) == 1


def test_record_call_with_cache(tracker):
    """Test recording with cached tokens."""
    record = tracker.record_call(
        model="gpt-5.1",
        role="reasoning",
        worker_id="worker_1",
        input_tokens=2000,
        output_tokens=1000,
        cache_input_tokens=500,
    )

    assert record.cache_input_tokens == 500
    assert record.worker_id == "worker_1"
    # Cost should be lower due to cached tokens
    assert record.cost_usd > 0


def test_multiple_calls_accumulate(tracker):
    """Test that multiple calls are accumulated correctly."""
    # Record multiple calls
    tracker.record_call("gpt-5", "auxiliary", None, 1000, 500, 0)
    tracker.record_call("gpt-5", "reasoning", "worker_1", 2000, 1000, 300)
    tracker.record_call("gpt-5-mini", "reasoning", "worker_2", 1500, 750, 0)

    assert len(tracker._records) == 3

    summary = tracker.get_summary()
    assert summary.total_calls == 3
    assert summary.total_input_tokens == 4500
    assert summary.total_output_tokens == 2250
    assert summary.total_cache_input_tokens == 300


def test_summary_by_model(tracker):
    """Test per-model aggregation in summary."""
    # Record calls to different models
    tracker.record_call("gpt-5", "auxiliary", None, 1000, 500, 0)
    tracker.record_call("gpt-5", "reasoning", "worker_1", 2000, 1000, 0)
    tracker.record_call("gpt-5-mini", "reasoning", "worker_2", 1500, 750, 0)

    summary = tracker.get_summary()

    # Check gpt-5 aggregation
    assert "gpt-5" in summary.by_model
    gpt5_stats = summary.by_model["gpt-5"]
    assert gpt5_stats.call_count == 2
    assert gpt5_stats.total_input_tokens == 3000
    assert gpt5_stats.total_output_tokens == 1500

    # Check gpt-5-mini aggregation
    assert "gpt-5-mini" in summary.by_model
    mini_stats = summary.by_model["gpt-5-mini"]
    assert mini_stats.call_count == 1
    assert mini_stats.total_input_tokens == 1500


def test_summary_by_role(tracker):
    """Test per-role aggregation in summary."""
    tracker.record_call("gpt-5", "auxiliary", None, 1000, 500, 0)
    tracker.record_call("gpt-5", "reasoning", "worker_1", 2000, 1000, 0)
    tracker.record_call("gpt-5", "reasoning", "worker_2", 1500, 750, 0)

    summary = tracker.get_summary()

    # Check auxiliary role
    assert "auxiliary" in summary.by_role
    aux_stats = summary.by_role["auxiliary"]
    assert aux_stats["call_count"] == 1
    assert aux_stats["total_input_tokens"] == 1000

    # Check reasoning role
    assert "reasoning" in summary.by_role
    reasoning_stats = summary.by_role["reasoning"]
    assert reasoning_stats["call_count"] == 2
    assert reasoning_stats["total_input_tokens"] == 3500


def test_worker_count(tracker):
    """Test that unique workers are counted correctly."""
    tracker.record_call("gpt-5", "auxiliary", None, 1000, 500, 0)
    tracker.record_call("gpt-5", "reasoning", "worker_1", 2000, 1000, 0)
    tracker.record_call("gpt-5", "reasoning", "worker_1", 1500, 750, 0)  # Same worker
    tracker.record_call("gpt-5", "reasoning", "worker_2", 1800, 900, 0)

    summary = tracker.get_summary()
    assert summary.worker_count == 2  # Only 2 unique workers


def test_empty_summary(tracker):
    """Test summary with no recorded calls."""
    summary = tracker.get_summary()

    assert summary.total_calls == 0
    assert summary.total_input_tokens == 0
    assert summary.total_cost_usd == 0.0
    assert len(summary.by_model) == 0
    assert len(summary.by_role) == 0
    assert summary.worker_count == 0


def test_callback_handler_extraction(tracker, mock_llm_result):
    """Test that callback handler correctly extracts usage from LLMResult."""
    callback = LangGraphCallbackHandler(tracker, role="auxiliary")

    # Simulate on_llm_end callback
    callback.on_llm_end(mock_llm_result)

    # Check that usage was recorded
    assert len(tracker._records) == 1
    record = tracker._records[0]
    assert record.model == "gpt-5"
    assert record.input_tokens == 1000
    assert record.output_tokens == 500
    assert record.cache_input_tokens == 200


def test_wrap_llm_adds_callback(tracker):
    """Test that wrapping LLM adds callback handler."""
    mock_llm = Mock()
    mock_llm.callbacks = []

    wrapped = tracker.wrap_llm(mock_llm, role="auxiliary")

    assert len(wrapped.callbacks) == 1
    assert isinstance(wrapped.callbacks[0], LangGraphCallbackHandler)
    assert wrapped.callbacks[0].role == "auxiliary"


def test_wrap_llm_auto_worker_id(tracker):
    """Test that wrapping reasoning LLM auto-generates worker IDs."""
    mock_llm1 = Mock()
    mock_llm1.callbacks = []
    mock_llm2 = Mock()
    mock_llm2.callbacks = []

    wrapped1 = tracker.wrap_llm(mock_llm1, role="reasoning")
    wrapped2 = tracker.wrap_llm(mock_llm2, role="reasoning")

    assert wrapped1.callbacks[0].worker_id == "worker_1"
    assert wrapped2.callbacks[0].worker_id == "worker_2"


def test_save_to_file(tracker, tmp_path):
    """Test saving pricing data to JSON file."""
    # Record some calls
    tracker.record_call("gpt-5", "auxiliary", None, 1000, 500, 0)
    tracker.record_call("gpt-5", "reasoning", "worker_1", 2000, 1000, 100)

    # Save to temp file
    output_file = tmp_path / "test_pricing.json"
    tracker.save_to_file(str(output_file))

    # Verify file exists and contains valid JSON
    assert output_file.exists()

    with open(output_file, "r") as f:
        data = json.load(f)

    # Check structure
    assert "summary" in data
    assert "detailed_calls" in data

    # Check summary
    assert data["summary"]["total_calls"] == 2
    assert data["summary"]["total_input_tokens"] == 3000
    assert data["summary"]["worker_count"] == 1

    # Check detailed calls
    assert len(data["detailed_calls"]) == 2
    assert data["detailed_calls"][0]["model"] == "gpt-5"


def test_pricing_calculation_accuracy(tracker):
    """Test that pricing calculations match expected values."""
    # gpt-5 pricing: input=$1.25/1M, output=$10.0/1M, cache=$0.125/1M
    record = tracker.record_call(
        model="gpt-5",
        role="auxiliary",
        worker_id=None,
        input_tokens=1_000_000,  # 1M tokens
        output_tokens=1_000_000,  # 1M tokens
        cache_input_tokens=0,
    )

    # Expected cost: $1.25 (input) + $10.0 (output) = $11.25
    assert abs(record.cost_usd - 11.25) < 0.01


def test_pricing_with_cache(tracker):
    """Test that cache tokens reduce cost correctly."""
    # gpt-5 pricing: input=$1.25/1M, cache=$0.125/1M
    record = tracker.record_call(
        model="gpt-5",
        role="auxiliary",
        worker_id=None,
        input_tokens=1_000_000,  # 1M tokens
        output_tokens=0,
        cache_input_tokens=500_000,  # 500K cached
    )

    # Expected cost:
    # - Billed input: 1M - 500K = 500K tokens at $1.25/1M = $0.625
    # - Cache: 500K tokens at $0.125/1M = $0.0625
    # - Total: $0.6875
    expected_cost = (500_000 / 1_000_000) * 1.25 + (500_000 / 1_000_000) * 0.125
    assert abs(record.cost_usd - expected_cost) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
