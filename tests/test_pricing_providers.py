import pytest
from unittest.mock import patch, MagicMock

from utils.pricing_providers import (
    ProviderPricingManager, 
    _strip_date_suffix,
    OpenAIUsageExtractor,
    AnthropicUsageExtractor,
    OpenAIPricingCalculator,
    AnthropicPricingCalculator,
    UsageMetrics,
    ProviderPricing
)
from utils.token_tracker import TokenTracker


##########################################
#         Mock Data                      #
##########################################

MOCK_PRICING_CONFIG = {
    "openai": {
        "gpt-4.1": {
            "input": 2.0,
            "output": 8.0,
            "cache_input": 0.5
        },
        "gpt-5": {
            "input": 1.25,
            "output": 10.0,
            "cache_input": 0.125
        },
        "gpt-5-mini": {
            "input": 0.25,
            "output": 2.0,
            "cache_input": 0.025
        },
        "o3": {
            "input": 3.5,
            "output": 14.0,
            "cache_input": 0.875
        }
    },
    "anthropic": {
        "claude-opus-4-0": {
            "input": 15.0,
            "output": 75.0,
            "cache_hits_and_refreshes": 0.3,
            "cache_write": 18.75
        },
        "claude-sonnet-4-0": {
            "input": 3.0,
            "output": 15.0,
            "cache_hits_and_refreshes": 0.3,
            "cache_write": 3.75
        },
        "claude-3-7-sonnet-latest": {
            "input": 3.0,
            "output": 15.0,
            "cache_hits_and_refreshes": 0.3,
            "cache_write": 3.75
        }
    }
}


@pytest.fixture
def mock_pricing_manager():
    """Create a ProviderPricingManager with mock pricing data."""
    with patch.object(ProviderPricingManager, '_load_pricing_config') as mock_load:
        mock_load.return_value = MOCK_PRICING_CONFIG
        return ProviderPricingManager()


@pytest.fixture
def mock_token_tracker():
    """Create a TokenTracker with mock pricing data."""
    with patch.object(ProviderPricingManager, '_load_pricing_config') as mock_load:
        mock_load.return_value = MOCK_PRICING_CONFIG
        return TokenTracker()


##########################################
#     Provider Detection Tests          #
##########################################

@pytest.mark.pricing
def test_provider_detection_openai(mock_pricing_manager):
    """Test OpenAI model provider detection."""
    # Standard OpenAI models
    assert mock_pricing_manager.get_provider_from_model("gpt-4") == "openai"
    assert mock_pricing_manager.get_provider_from_model("gpt-5") == "openai"
    assert mock_pricing_manager.get_provider_from_model("gpt-5-mini") == "openai"
    assert mock_pricing_manager.get_provider_from_model("gpt-4.1") == "openai"
    
    # O-series models
    assert mock_pricing_manager.get_provider_from_model("o1-preview") == "openai"
    assert mock_pricing_manager.get_provider_from_model("o3") == "openai"
    
    # ChatGPT models
    assert mock_pricing_manager.get_provider_from_model("chatgpt-4o") == "openai"


@pytest.mark.pricing
def test_provider_detection_anthropic(mock_pricing_manager):
    """Test Anthropic model provider detection."""
    # Claude models
    assert mock_pricing_manager.get_provider_from_model("claude-sonnet-4-0") == "anthropic"
    assert mock_pricing_manager.get_provider_from_model("claude-3-7-sonnet-latest") == "anthropic"
    assert mock_pricing_manager.get_provider_from_model("claude-opus-4-0") == "anthropic"
    
    # Direct model type names
    assert mock_pricing_manager.get_provider_from_model("sonnet-4") == "anthropic"
    assert mock_pricing_manager.get_provider_from_model("haiku-3") == "anthropic"
    assert mock_pricing_manager.get_provider_from_model("opus-4") == "anthropic"


@pytest.mark.pricing
def test_provider_detection_unknown_model(mock_pricing_manager):
    """Test that unknown models raise ValueError."""
    with pytest.raises(ValueError, match="Unknown model 'unknown-model'"):
        mock_pricing_manager.get_provider_from_model("unknown-model")
    
    with pytest.raises(ValueError, match="Unknown model 'llama-7b'"):
        mock_pricing_manager.get_provider_from_model("llama-7b")


##########################################
#     Date Suffix Stripping Tests       #
##########################################

@pytest.mark.pricing
def test_strip_date_suffix_openai_format():
    """Test stripping OpenAI-style date suffixes (-YYYY-MM-DD)."""
    # With date suffix
    assert _strip_date_suffix("gpt-5-2025-08-07") == "gpt-5"
    assert _strip_date_suffix("gpt-5-mini-2025-08-07") == "gpt-5-mini"
    assert _strip_date_suffix("claude-sonnet-4-0-2025-08-07") == "claude-sonnet-4-0"
    
    # Edge cases
    assert _strip_date_suffix("model-2024-12-31") == "model"
    assert _strip_date_suffix("model-2025-01-01") == "model"


@pytest.mark.pricing
def test_strip_date_suffix_anthropic_format():
    """Test stripping Anthropic-style date suffixes (-YYYYMMDD)."""
    # With date suffix
    assert _strip_date_suffix("claude-sonnet-4-20250514") == "claude-sonnet-4"
    assert _strip_date_suffix("claude-3-7-sonnet-20250219") == "claude-3-7-sonnet"
    assert _strip_date_suffix("claude-opus-4-20250514") == "claude-opus-4"
    
    # Edge cases
    assert _strip_date_suffix("model-20241231") == "model"
    assert _strip_date_suffix("model-20250101") == "model"


@pytest.mark.pricing
def test_strip_date_suffix_no_change():
    """Test that models without date suffixes remain unchanged."""
    # No suffix
    assert _strip_date_suffix("gpt-5") == "gpt-5"
    assert _strip_date_suffix("claude-sonnet-4-0") == "claude-sonnet-4-0"
    assert _strip_date_suffix("model") == "model"
    
    # Partial date patterns (should not match)
    assert _strip_date_suffix("gpt-5-2025") == "gpt-5-2025"
    assert _strip_date_suffix("gpt-5-25-08-07") == "gpt-5-25-08-07"
    assert _strip_date_suffix("model-123456") == "model-123456"


##########################################
#        Pricing Retrieval Tests        #
##########################################

@pytest.mark.pricing
def test_pricing_retrieval_openai(mock_pricing_manager):
    """Test pricing retrieval for OpenAI models."""
    # Test gpt-4.1 pricing
    pricing = mock_pricing_manager.get_pricing("gpt-4.1")
    assert pricing.input_price == 2.0
    assert pricing.output_price == 8.0
    assert pricing.cache_price == 0.5
    assert pricing.cache_hits_and_refreshes_price == 0.0
    assert pricing.cache_write_price == 0.0
    
    # Test gpt-5 pricing
    pricing = mock_pricing_manager.get_pricing("gpt-5")
    assert pricing.input_price == 1.25
    assert pricing.output_price == 10.0
    assert pricing.cache_price == 0.125


@pytest.mark.pricing
def test_pricing_retrieval_anthropic(mock_pricing_manager):
    """Test pricing retrieval for Anthropic models."""
    # Test claude-sonnet-4-0 pricing
    pricing = mock_pricing_manager.get_pricing("claude-sonnet-4-0")
    assert pricing.input_price == 3.0
    assert pricing.output_price == 15.0
    assert pricing.cache_hits_and_refreshes_price == 0.3
    assert pricing.cache_write_price == 3.75
    assert pricing.cache_price == 0.0  # OpenAI-style cache not used
    
    # Test claude-opus-4-0 pricing
    pricing = mock_pricing_manager.get_pricing("claude-opus-4-0")
    assert pricing.input_price == 15.0
    assert pricing.output_price == 75.0
    assert pricing.cache_hits_and_refreshes_price == 0.3
    assert pricing.cache_write_price == 18.75


@pytest.mark.pricing
def test_pricing_retrieval_with_date_suffix(mock_pricing_manager):
    """Test pricing retrieval for models with date suffixes."""
    # OpenAI models with date suffix should map to base model
    pricing = mock_pricing_manager.get_pricing("gpt-4.1-2025-01-15")
    assert pricing.input_price == 2.0
    assert pricing.output_price == 8.0
    
    # Anthropic models with date suffix should map to base model
    pricing = mock_pricing_manager.get_pricing("claude-sonnet-4-20250514")
    assert pricing.input_price == 3.0
    assert pricing.output_price == 15.0


@pytest.mark.pricing
def test_pricing_retrieval_anthropic_model_variations(mock_pricing_manager):
    """Test pricing retrieval for Anthropic model name variations."""
    # Test model variations that should map to known models
    test_cases = [
        ("claude-sonnet-4-20250514", 3.0, 15.0),  # Maps to claude-sonnet-4-0
        ("claude-opus-4-20250514", 15.0, 75.0),   # Maps to claude-opus-4-0
        ("claude-3-7-sonnet-20250219", 3.0, 15.0), # Maps to claude-3-7-sonnet-latest
    ]
    
    for model, expected_input, expected_output in test_cases:
        pricing = mock_pricing_manager.get_pricing(model)
        assert pricing.input_price == expected_input
        assert pricing.output_price == expected_output


@pytest.mark.pricing
def test_pricing_retrieval_unknown_model(mock_pricing_manager):
    """Test pricing retrieval for unknown models returns zeros."""
    # Unknown models should return zero pricing
    pricing = mock_pricing_manager.get_pricing("claude-unknown-model")
    assert pricing.input_price == 0.0
    assert pricing.output_price == 0.0
    assert pricing.cache_hits_and_refreshes_price == 0.0
    assert pricing.cache_write_price == 0.0


@pytest.mark.pricing
def test_pricing_retrieval_unsupported_provider(mock_pricing_manager):
    """Test that unsupported providers raise ValueError."""
    with pytest.raises(ValueError, match="Unsupported provider 'unknown'"):
        mock_pricing_manager.get_pricing("test-model", provider="unknown")


##########################################
#      Usage Extractor Tests            #
##########################################

class MockOpenAIUsage:
    def __init__(self, input_tokens=0, output_tokens=0, cached_tokens=0, reasoning_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        if cached_tokens > 0:
            self.input_tokens_details = MockInputDetails(cached_tokens)
        if reasoning_tokens > 0:
            self.output_tokens_details = MockOutputDetails(reasoning_tokens)

class MockInputDetails:
    def __init__(self, cached_tokens):
        self.cached_tokens = cached_tokens

class MockOutputDetails:
    def __init__(self, reasoning_tokens):
        self.reasoning_tokens = reasoning_tokens

class MockOpenAIResponse:
    def __init__(self, input_tokens=0, output_tokens=0, cached_tokens=0, reasoning_tokens=0):
        self.id = "openai-req-123"
        self.usage = MockOpenAIUsage(input_tokens, output_tokens, cached_tokens, reasoning_tokens)


@pytest.mark.usage_extraction
def test_openai_usage_extractor_basic():
    """Test OpenAI usage extraction with basic tokens."""
    extractor = OpenAIUsageExtractor()
    response = MockOpenAIResponse(input_tokens=1000, output_tokens=500)
    
    usage = extractor.extract_usage(response)
    
    assert usage.input_tokens == 1000
    assert usage.output_tokens == 500
    assert usage.cache_tokens == 0
    assert usage.cache_write_tokens == 0
    assert usage.reasoning_tokens == 0
    assert usage.request_id == "openai-req-123"


@pytest.mark.usage_extraction
def test_openai_usage_extractor_with_cache():
    """Test OpenAI usage extraction with cache tokens."""
    extractor = OpenAIUsageExtractor()
    response = MockOpenAIResponse(input_tokens=1000, output_tokens=500, cached_tokens=200)
    
    usage = extractor.extract_usage(response)
    
    assert usage.input_tokens == 1000
    assert usage.output_tokens == 500
    assert usage.cache_tokens == 200
    assert usage.reasoning_tokens == 0


@pytest.mark.usage_extraction
def test_openai_usage_extractor_with_reasoning():
    """Test OpenAI usage extraction with reasoning tokens."""
    extractor = OpenAIUsageExtractor()
    response = MockOpenAIResponse(input_tokens=1000, output_tokens=500, reasoning_tokens=100)
    
    usage = extractor.extract_usage(response)
    
    assert usage.input_tokens == 1000
    assert usage.output_tokens == 500
    assert usage.reasoning_tokens == 100


@pytest.mark.usage_extraction
def test_openai_usage_extractor_no_usage():
    """Test OpenAI usage extraction when no usage data is present."""
    extractor = OpenAIUsageExtractor()
    
    class MockResponseNoUsage:
        def __init__(self):
            self.id = "test-id"
            # No usage attribute
    
    response = MockResponseNoUsage()
    usage = extractor.extract_usage(response)
    
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.cache_tokens == 0
    assert usage.request_id is None


class MockAnthropicUsage:
    def __init__(self, input_tokens=0, output_tokens=0, cache_read=0, cache_write=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        if cache_read > 0:
            self.cache_read_input_tokens = cache_read
        if cache_write > 0:
            self.cache_creation_input_tokens = cache_write

class MockAnthropicResponse:
    def __init__(self, input_tokens=0, output_tokens=0, cache_read=0, cache_write=0):
        self.id = "msg_anthropic_123"
        self.usage = MockAnthropicUsage(input_tokens, output_tokens, cache_read, cache_write)


@pytest.mark.usage_extraction
def test_anthropic_usage_extractor_basic():
    """Test Anthropic usage extraction with basic tokens."""
    extractor = AnthropicUsageExtractor()
    response = MockAnthropicResponse(input_tokens=1000, output_tokens=500)
    
    usage = extractor.extract_usage(response)
    
    assert usage.input_tokens == 1000
    assert usage.output_tokens == 500
    assert usage.cache_tokens == 0
    assert usage.cache_write_tokens == 0
    assert usage.reasoning_tokens == 0
    assert usage.request_id == "msg_anthropic_123"


@pytest.mark.usage_extraction
def test_anthropic_usage_extractor_with_cache():
    """Test Anthropic usage extraction with cache tokens."""
    extractor = AnthropicUsageExtractor()
    response = MockAnthropicResponse(input_tokens=1000, output_tokens=500, cache_read=100, cache_write=50)
    
    usage = extractor.extract_usage(response)
    
    assert usage.input_tokens == 1000
    assert usage.output_tokens == 500
    assert usage.cache_tokens == 100  # cache_read_input_tokens
    assert usage.cache_write_tokens == 50  # cache_creation_input_tokens
    assert usage.reasoning_tokens == 0


##########################################
#      Pricing Calculator Tests         #
##########################################

@pytest.mark.pricing_calculation
def test_openai_pricing_calculator():
    """Test OpenAI pricing calculation logic."""
    calculator = OpenAIPricingCalculator()
    
    usage = UsageMetrics(
        input_tokens=1000,
        output_tokens=500,
        cache_tokens=200,
        reasoning_tokens=100
    )
    
    pricing = ProviderPricing(
        input_price=2.0,
        output_price=8.0,
        cache_price=0.5,
        reasoning_price=4.0
    )
    
    cost = calculator.calculate_cost(usage, pricing)
    
    # OpenAI calculation: billed_input = input - cache = 1000 - 200 = 800
    # Cost = (800/1M * 2.0) + (500/1M * 8.0) + (200/1M * 0.5) + (100/1M * 4.0)
    # Cost = 0.0016 + 0.004 + 0.0001 + 0.0004 = 0.0061
    expected_cost = 0.0061
    assert cost == pytest.approx(expected_cost, rel=1e-9)


@pytest.mark.pricing_calculation
def test_anthropic_pricing_calculator():
    """Test Anthropic pricing calculation logic."""
    calculator = AnthropicPricingCalculator()
    
    usage = UsageMetrics(
        input_tokens=1000,
        output_tokens=500,
        cache_tokens=100,
        cache_write_tokens=50
    )
    
    pricing = ProviderPricing(
        input_price=3.0,
        output_price=15.0,
        cache_hits_and_refreshes_price=0.3,
        cache_write_price=3.75
    )
    
    cost = calculator.calculate_cost(usage, pricing)
    
    # Anthropic calculation: bills all input tokens (no deduction for cache)
    # Cost = (1000/1M * 3.0) + (500/1M * 15.0) + (100/1M * 0.3) + (50/1M * 3.75)
    # Cost = 0.003 + 0.0075 + 0.00003 + 0.0001875 = 0.0107175
    expected_cost = 0.0107175
    assert cost == pytest.approx(expected_cost, rel=1e-9)


##########################################
#     Integration Tests                  #
##########################################

@pytest.mark.integration
def test_extract_usage_and_cost_openai(mock_pricing_manager):
    """Test end-to-end usage extraction and cost calculation for OpenAI."""
    response = MockOpenAIResponse(input_tokens=1000, output_tokens=500, cached_tokens=200)
    
    usage, cost = mock_pricing_manager.extract_usage_and_cost(response, "gpt-4.1")
    
    assert usage.input_tokens == 1000
    assert usage.output_tokens == 500
    assert usage.cache_tokens == 200
    assert cost > 0
    
    # Verify calculation matches expected logic
    # gpt-4.1: input=2.0, output=8.0, cache_input=0.5
    # billed_input = 1000 - 200 = 800
    # cost = (800/1M * 2.0) + (500/1M * 8.0) + (200/1M * 0.5) = 0.0057
    expected_cost = 0.0057
    assert cost == pytest.approx(expected_cost, rel=1e-9)


@pytest.mark.integration
def test_extract_usage_and_cost_anthropic(mock_pricing_manager):
    """Test end-to-end usage extraction and cost calculation for Anthropic."""
    response = MockAnthropicResponse(input_tokens=1000, output_tokens=500, cache_read=100, cache_write=50)
    
    usage, cost = mock_pricing_manager.extract_usage_and_cost(response, "claude-sonnet-4-0")
    
    assert usage.input_tokens == 1000
    assert usage.output_tokens == 500
    assert usage.cache_tokens == 100
    assert usage.cache_write_tokens == 50
    assert cost > 0
    
    # Verify calculation matches expected logic
    # claude-sonnet-4-0: input=3.0, output=15.0, cache_hits_and_refreshes=0.3, cache_write=3.75
    # cost = (1000/1M * 3.0) + (500/1M * 15.0) + (100/1M * 0.3) + (50/1M * 3.75) = 0.0107175
    expected_cost = 0.0107175
    assert cost == pytest.approx(expected_cost, rel=1e-9)


@pytest.mark.integration
def test_extract_usage_and_cost_unknown_provider(mock_pricing_manager):
    """Test that unknown providers raise ValueError."""
    response = MockOpenAIResponse(input_tokens=1000, output_tokens=500)
    
    with pytest.raises(ValueError, match="Unknown model 'unknown-model'"):
        mock_pricing_manager.extract_usage_and_cost(response, "unknown-model")


##########################################
#        Token Tracker Tests            #
##########################################

@pytest.mark.token_tracker
def test_tracker_openai_response():
    """Test TokenTracker with OpenAI response."""
    tracker = TokenTracker()
    mock_resp = MockOpenAIResponse(input_tokens=1000, output_tokens=500, cached_tokens=200)
    record = tracker.record_from_response(mock_resp, "gpt-4.1")
    
    assert record.model == "gpt-4.1"
    assert record.request_id == "openai-req-123"
    assert record.input_tokens == 1000
    assert record.output_tokens == 500
    assert record.cache_tokens == 200
    assert record.cache_write_tokens == 0
    assert record.cost_usd > 0
    
    totals = tracker.totals()
    assert totals["calls"] == 1
    assert totals["input_tokens"] == 1000
    assert totals["output_tokens"] == 500
    assert totals["cache_tokens"] == 200
    assert totals["cache_write_tokens"] == 0


@pytest.mark.token_tracker
def test_tracker_anthropic_response():
    """Test TokenTracker with Anthropic response."""
    tracker = TokenTracker()
    mock_resp = MockAnthropicResponse(input_tokens=1000, output_tokens=500, cache_read=100, cache_write=50)
    record = tracker.record_from_response(mock_resp, "claude-sonnet-4-0")
    
    assert record.model == "claude-sonnet-4-0"
    assert record.request_id == "msg_anthropic_123"
    assert record.input_tokens == 1000
    assert record.output_tokens == 500
    assert record.cache_tokens == 100
    assert record.cache_write_tokens == 50
    assert record.cost_usd > 0
    
    totals = tracker.totals()
    assert totals["calls"] == 1
    assert totals["input_tokens"] == 1000
    assert totals["output_tokens"] == 500
    assert totals["cache_tokens"] == 100
    assert totals["cache_write_tokens"] == 50


@pytest.mark.token_tracker
def test_tracker_multiple_providers():
    """Test TokenTracker with multiple providers."""
    tracker = TokenTracker()
    
    # Record OpenAI call
    openai_resp = MockOpenAIResponse(input_tokens=500, output_tokens=200, cached_tokens=100)
    tracker.record_from_response(openai_resp, "gpt-4.1")
    
    # Record Anthropic call
    anthropic_resp = MockAnthropicResponse(input_tokens=800, output_tokens=300, cache_read=50, cache_write=25)
    tracker.record_from_response(anthropic_resp, "claude-sonnet-4-0")
    
    totals = tracker.totals()
    assert totals["calls"] == 2
    assert totals["input_tokens"] == 1300  # 500 + 800
    assert totals["output_tokens"] == 500  # 200 + 300
    assert totals["cache_tokens"] == 150   # 100 + 50
    assert totals["cache_write_tokens"] == 25  # 0 + 25
    assert totals["cost_usd"] > 0


@pytest.mark.token_tracker
def test_tracker_date_suffix_models():
    """Test TokenTracker with date-suffixed models."""
    tracker = TokenTracker()
    
    # Test OpenAI model with date suffix
    openai_resp = MockOpenAIResponse(input_tokens=1000, output_tokens=500)
    record1 = tracker.record_from_response(openai_resp, "gpt-4.1-2025-01-15")
    assert record1.cost_usd > 0  # Should find pricing for gpt-4.1
    
    # Test Anthropic model with date suffix
    anthropic_resp = MockAnthropicResponse(input_tokens=1000, output_tokens=500)
    record2 = tracker.record_from_response(anthropic_resp, "claude-sonnet-4-20250514")
    assert record2.cost_usd > 0  # Should find pricing for claude-sonnet-4-0


@pytest.mark.token_tracker
def test_tracker_unknown_model_raises_error():
    """Test TokenTracker with unknown model raises ValueError."""
    tracker = TokenTracker()
    mock_resp = MockOpenAIResponse(input_tokens=1000, output_tokens=500)
    
    with pytest.raises(ValueError, match="Unknown model 'unknown-model'"):
        tracker.record_from_response(mock_resp, "unknown-model")


##########################################
#         Edge Case Tests               #
##########################################

@pytest.mark.edge_cases
def test_zero_token_usage():
    """Test handling of zero token usage."""
    calculator = OpenAIPricingCalculator()
    usage = UsageMetrics(input_tokens=0, output_tokens=0, cache_tokens=0)
    pricing = ProviderPricing(input_price=2.0, output_price=8.0, cache_price=0.5)
    
    cost = calculator.calculate_cost(usage, pricing)
    assert cost == 0.0


@pytest.mark.edge_cases
def test_negative_token_handling():
    """Test that negative tokens are handled gracefully."""
    extractor = OpenAIUsageExtractor()
    
    class MockNegativeUsage:
        def __init__(self):
            self.input_tokens = -100  # Negative value
            self.output_tokens = 500
    
    class MockNegativeResponse:
        def __init__(self):
            self.id = "test"
            self.usage = MockNegativeUsage()
    
    response = MockNegativeResponse()
    usage = extractor.extract_usage(response)
    
    # Should handle negative values gracefully (convert to 0)
    assert usage.input_tokens == 0
    assert usage.output_tokens == 500


@pytest.mark.edge_cases
def test_invalid_token_types():
    """Test handling of invalid token value types."""
    extractor = OpenAIUsageExtractor()
    
    class MockInvalidUsage:
        def __init__(self):
            self.input_tokens = "invalid"  # String instead of int
            self.output_tokens = None      # None value
    
    class MockInvalidResponse:
        def __init__(self):
            self.id = "test"
            self.usage = MockInvalidUsage()
    
    response = MockInvalidResponse()
    usage = extractor.extract_usage(response)
    
    # Should handle invalid types gracefully (convert to 0)
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0