"""
Comprehensive test suite for pricing_providers.py and token_tracker.py

Tests cover:
- Date suffix stripping
- Usage extraction from provider responses
- Cost calculations
- Model name resolution and mappings
- Provider pricing manager functionality
- Token tracker integration
- Edge cases and error handling
"""

import pytest
from unittest.mock import Mock, patch, mock_open
from typing import Dict, Any
from datetime import datetime

from utils.pricing_providers import (
    ProviderPricingManager,
    OpenAIUsageExtractor,
    AnthropicUsageExtractor,
    OpenAIPricingCalculator,
    AnthropicPricingCalculator,
    UsageMetrics,
    ProviderPricing,
    _strip_date_suffix,
    PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC,
    ANTHROPIC_MODEL_MAPPINGS,
    TOKENS_PER_MILLION,
)
from utils.token_tracker import TokenTracker, TokenUsage


class TestDateSuffixStripping:
    """Test date suffix stripping functionality."""
    
    @pytest.mark.parametrize("model, expected", [
        # OpenAI format: -YYYY-MM-DD
        ("gpt-5-2025-01-15", "gpt-5"),
        ("gpt-5-mini-2024-12-31", "gpt-5-mini"),
        ("o3-2025-08-07", "o3"),
        ("model-2023-06-15", "model"),
        
        # Anthropic format: -YYYYMMDD
        ("claude-sonnet-4-20250514", "claude-sonnet-4"),
        ("claude-opus-4-20241022", "claude-opus-4"),
        ("model-20250101", "model"),
        
        # No suffix cases
        ("gpt-5", "gpt-5"),
        ("claude-sonnet-4", "claude-sonnet-4"),
        ("model", "model"),
        
        # Partial/invalid date patterns (should remain unchanged)
        ("gpt-5-2025", "gpt-5-2025"),
        ("gpt-5-25-08-07", "gpt-5-25-08-07"),
        ("model-123456", "model-123456"),
        ("model-12345678", "model"),  # This is valid YYYYMMDD format
    ])
    def test_strip_date_suffix(self, model: str, expected: str):
        """Test date suffix stripping with various formats."""
        assert _strip_date_suffix(model) == expected


class TestUsageExtractors:
    """Test usage extraction from provider responses."""
    
    class TestOpenAIUsageExtractor:
        """Test OpenAI usage extraction."""
        
        @pytest.fixture
        def extractor(self):
            return OpenAIUsageExtractor()
        
        def test_extract_basic_usage(self, extractor):
            """Test basic token extraction."""
            mock_usage = Mock()
            mock_usage.input_tokens = 1000
            mock_usage.output_tokens = 500
            
            mock_response = Mock()
            mock_response.id = "req_123"
            mock_response.usage = mock_usage
            
            result = extractor.extract_usage(mock_response)
            
            assert result.input_tokens == 1000
            assert result.output_tokens == 500
            assert result.cache_tokens == 0
            assert result.reasoning_tokens == 0
            assert result.request_id == "req_123"
        
        def test_extract_with_cache_tokens(self, extractor):
            """Test extraction with cache tokens."""
            mock_input_details = Mock()
            mock_input_details.cached_tokens = 200
            
            mock_usage = Mock()
            mock_usage.input_tokens = 1000
            mock_usage.output_tokens = 500
            mock_usage.input_tokens_details = mock_input_details
            
            mock_response = Mock()
            mock_response.id = "req_123"
            mock_response.usage = mock_usage
            
            result = extractor.extract_usage(mock_response)
            
            assert result.input_tokens == 1000
            assert result.output_tokens == 500
            assert result.cache_tokens == 200
            assert result.reasoning_tokens == 0
        
        def test_extract_with_reasoning_tokens(self, extractor):
            """Test extraction with reasoning tokens."""
            mock_output_details = Mock()
            mock_output_details.reasoning_tokens = 150
            
            mock_usage = Mock()
            mock_usage.input_tokens = 1000
            mock_usage.output_tokens = 500
            mock_usage.output_tokens_details = mock_output_details
            
            mock_response = Mock()
            mock_response.id = "req_123"
            mock_response.usage = mock_usage
            
            result = extractor.extract_usage(mock_response)
            
            assert result.input_tokens == 1000
            assert result.output_tokens == 500
            assert result.reasoning_tokens == 150
        
        def test_extract_no_usage_data(self, extractor):
            """Test handling when no usage data is present."""
            mock_response = Mock()
            mock_response.id = "req_123"
            # No usage attribute
            del mock_response.usage
            
            result = extractor.extract_usage(mock_response)
            
            assert result.input_tokens == 0
            assert result.output_tokens == 0
            assert result.cache_tokens == 0
            assert result.reasoning_tokens == 0
            assert result.request_id is None
        
        @pytest.mark.parametrize("invalid_value", [None, "invalid", -100, [1, 2, 3]])
        def test_extract_invalid_token_values(self, extractor, invalid_value):
            """Test handling of invalid token values."""
            mock_usage = Mock()
            mock_usage.input_tokens = invalid_value
            mock_usage.output_tokens = 500
            
            mock_response = Mock()
            mock_response.id = "req_123"
            mock_response.usage = mock_usage
            
            result = extractor.extract_usage(mock_response)
            
            # Invalid input_tokens should become 0, output_tokens should remain 500
            assert result.input_tokens == 0
            assert result.output_tokens == 500

    
    class TestAnthropicUsageExtractor:
        """Test Anthropic usage extraction."""
        
        @pytest.fixture
        def extractor(self):
            return AnthropicUsageExtractor()
        
        def test_extract_basic_usage(self, extractor):
            """Test basic token extraction."""
            mock_usage = Mock()
            mock_usage.input_tokens = 1000
            mock_usage.output_tokens = 500
            
            mock_response = Mock()
            mock_response.id = "msg_123"
            mock_response.usage = mock_usage
            
            result = extractor.extract_usage(mock_response)
            
            assert result.input_tokens == 1000
            assert result.output_tokens == 500
            assert result.cache_tokens == 0
            assert result.cache_write_tokens == 0
            assert result.reasoning_tokens == 0
            assert result.request_id == "msg_123"
        
        def test_extract_with_cache_tokens(self, extractor):
            """Test extraction with cache tokens."""
            mock_usage = Mock()
            mock_usage.input_tokens = 1000
            mock_usage.output_tokens = 500
            mock_usage.cache_read_input_tokens = 100
            mock_usage.cache_creation_input_tokens = 50
            
            mock_response = Mock()
            mock_response.id = "msg_123"
            mock_response.usage = mock_usage
            
            result = extractor.extract_usage(mock_response)
            
            assert result.input_tokens == 1000
            assert result.output_tokens == 500
            assert result.cache_tokens == 100
            assert result.cache_write_tokens == 50
        
        def test_extract_no_usage_data(self, extractor):
            """Test handling when no usage data is present."""
            mock_response = Mock()
            mock_response.id = "msg_123"
            # No usage attribute
            del mock_response.usage
            
            result = extractor.extract_usage(mock_response)
            
            assert result.input_tokens == 0
            assert result.output_tokens == 0
            assert result.cache_tokens == 0
            assert result.cache_write_tokens == 0
            assert result.reasoning_tokens == 0
            assert result.request_id is None


class TestPricingCalculators:
    """Test pricing calculation logic."""
    
    class TestOpenAIPricingCalculator:
        """Test OpenAI pricing calculations."""
        
        @pytest.fixture
        def calculator(self):
            return OpenAIPricingCalculator()
        
        @pytest.fixture
        def sample_pricing(self):
            return ProviderPricing(
                input_price=2.0,
                output_price=8.0,
                cache_price=0.5,
                reasoning_price=4.0
            )
        
        def test_basic_cost_calculation(self, calculator, sample_pricing):
            """Test basic cost calculation without cache or reasoning."""
            usage = UsageMetrics(
                input_tokens=1000,
                output_tokens=500
            )
            
            cost = calculator.calculate_cost(usage, sample_pricing)
            
            # Expected: (1000/1M * 2.0) + (500/1M * 8.0) = 0.002 + 0.004 = 0.006
            expected = 0.006
            assert cost == pytest.approx(expected, rel=1e-9)
        
        def test_cost_calculation_with_cache(self, calculator, sample_pricing):
            """Test cost calculation with cache tokens (OpenAI deducts cache from input)."""
            usage = UsageMetrics(
                input_tokens=1000,
                output_tokens=500,
                cache_tokens=200
            )
            
            cost = calculator.calculate_cost(usage, sample_pricing)
            
            # Expected: 
            # billed_input = 1000 - 200 = 800
            # (800/1M * 2.0) + (500/1M * 8.0) + (200/1M * 0.5) = 0.0016 + 0.004 + 0.0001 = 0.0057
            expected = 0.0057
            assert cost == pytest.approx(expected, rel=1e-9)
        
        def test_cost_calculation_with_reasoning(self, calculator, sample_pricing):
            """Test cost calculation with reasoning tokens."""
            usage = UsageMetrics(
                input_tokens=1000,
                output_tokens=500,
                reasoning_tokens=100
            )
            
            cost = calculator.calculate_cost(usage, sample_pricing)
            
            # Expected: (1000/1M * 2.0) + (500/1M * 8.0) + (100/1M * 4.0) = 0.002 + 0.004 + 0.0004 = 0.0064
            expected = 0.0064
            assert cost == pytest.approx(expected, rel=1e-9)
        
        def test_cost_calculation_cache_exceeds_input(self, calculator, sample_pricing):
            """Test that billed input cannot go below zero."""
            usage = UsageMetrics(
                input_tokens=100,
                output_tokens=500,
                cache_tokens=200  # More cache than input
            )
            
            cost = calculator.calculate_cost(usage, sample_pricing)
            
            # billed_input should be max(100 - 200, 0) = 0
            # Expected: (0/1M * 2.0) + (500/1M * 8.0) + (200/1M * 0.5) = 0 + 0.004 + 0.0001 = 0.0041
            expected = 0.0041
            assert cost == pytest.approx(expected, rel=1e-9)
        
        def test_zero_usage_zero_cost(self, calculator, sample_pricing):
            """Test that zero usage results in zero cost."""
            usage = UsageMetrics()
            
            cost = calculator.calculate_cost(usage, sample_pricing)
            
            assert cost == 0.0
    
    class TestAnthropicPricingCalculator:
        """Test Anthropic pricing calculations."""
        
        @pytest.fixture
        def calculator(self):
            return AnthropicPricingCalculator()
        
        @pytest.fixture
        def sample_pricing(self):
            return ProviderPricing(
                input_price=3.0,
                output_price=15.0,
                cache_hits_and_refreshes_price=0.3,
                cache_write_price=3.75
            )
        
        def test_basic_cost_calculation(self, calculator, sample_pricing):
            """Test basic cost calculation without cache."""
            usage = UsageMetrics(
                input_tokens=1000,
                output_tokens=500
            )
            
            cost = calculator.calculate_cost(usage, sample_pricing)
            
            # Expected: (1000/1M * 3.0) + (500/1M * 15.0) = 0.003 + 0.0075 = 0.0105
            expected = 0.0105
            assert cost == pytest.approx(expected, rel=1e-9)
        
        def test_cost_calculation_with_cache(self, calculator, sample_pricing):
            """Test cost calculation with cache tokens (Anthropic bills all input tokens)."""
            usage = UsageMetrics(
                input_tokens=1000,
                output_tokens=500,
                cache_tokens=100,
                cache_write_tokens=50
            )
            
            cost = calculator.calculate_cost(usage, sample_pricing)
            
            # Expected: 
            # Input: (1000/1M * 3.0) = 0.003
            # Output: (500/1M * 15.0) = 0.0075
            # Cache read: (100/1M * 0.3) = 0.00003
            # Cache write: (50/1M * 3.75) = 0.0001875
            # Total: 0.003 + 0.0075 + 0.00003 + 0.0001875 = 0.0107175
            expected = 0.0107175
            assert cost == pytest.approx(expected, rel=1e-9)
        
        def test_zero_usage_zero_cost(self, calculator, sample_pricing):
            """Test that zero usage results in zero cost."""
            usage = UsageMetrics()
            
            cost = calculator.calculate_cost(usage, sample_pricing)
            
            assert cost == 0.0


class TestProviderPricingManager:
    """Test the main pricing manager functionality."""
    
    @pytest.fixture
    def mock_pricing_config(self):
        """Mock pricing configuration for testing."""
        return {
            "openai": {
                "gpt-5": {
                    "input": 1.25,
                    "output": 10.0,
                    "cache_input": 0.125,
                    "reasoning": 5.0
                },
                "gpt-4.1": {
                    "input": 2.0,
                    "output": 8.0,
                    "cache_input": 0.5
                }
            },
            "anthropic": {
                "claude-opus-4": {
                    "input": 15.0,
                    "output": 75.0,
                    "cache_hits_and_refreshes": 1.5,
                    "cache_write": 18.75
                },
                "claude-sonnet-4": {
                    "input": 3.0,
                    "output": 15.0,
                    "cache_hits_and_refreshes": 0.3,
                    "cache_write": 3.75
                },
                "claude-sonnet-3-7": {
                    "input": 3.0,
                    "output": 15.0,
                    "cache_hits_and_refreshes": 0.3,
                    "cache_write": 3.75
                }
            }
        }
    
    @pytest.fixture
    def pricing_manager(self, mock_pricing_config):
        """Create a pricing manager with mocked config."""
        with patch.object(ProviderPricingManager, '_load_pricing_config') as mock_load:
            mock_load.return_value = mock_pricing_config
            return ProviderPricingManager()
    
    class TestModelResolution:
        """Test model name resolution and mapping."""
        
        def test_exact_model_match_openai(self, pricing_manager):
            """Test exact model name matching for OpenAI."""
            pricing = pricing_manager.get_pricing("gpt-5", PROVIDER_OPENAI)
            
            assert pricing.input_price == 1.25
            assert pricing.output_price == 10.0
            assert pricing.cache_price == 0.125
            assert pricing.reasoning_price == 5.0
        
        def test_exact_model_match_anthropic(self, pricing_manager):
            """Test exact model name matching for Anthropic."""
            pricing = pricing_manager.get_pricing("claude-sonnet-4", PROVIDER_ANTHROPIC)
            
            assert pricing.input_price == 3.0
            assert pricing.output_price == 15.0
            assert pricing.cache_hits_and_refreshes_price == 0.3
            assert pricing.cache_write_price == 3.75
        
        @pytest.mark.parametrize("model_with_date, base_model", [
            ("gpt-5-2025-01-15", "gpt-5"),
            ("gpt-4.1-2024-12-31", "gpt-4.1"),
        ])
        def test_openai_date_suffix_stripping(self, pricing_manager, model_with_date, base_model):
            """Test OpenAI date suffix stripping."""
            pricing_with_date = pricing_manager.get_pricing(model_with_date, PROVIDER_OPENAI)
            pricing_base = pricing_manager.get_pricing(base_model, PROVIDER_OPENAI)
            
            assert pricing_with_date.input_price == pricing_base.input_price
            assert pricing_with_date.output_price == pricing_base.output_price
        
        @pytest.mark.parametrize("model_variation, canonical", [
            ("claude-opus-4-0", "claude-opus-4"),
            ("claude-opus-4-20250514", "claude-opus-4"),
            ("claude-4-opus-20250514", "claude-opus-4"),
            ("claude-sonnet-4-0", "claude-sonnet-4"),
            ("claude-sonnet-4-20250514", "claude-sonnet-4"),
            ("claude-3-7-sonnet-latest", "claude-sonnet-3-7"),
        ])
        def test_anthropic_model_mappings(self, pricing_manager, model_variation, canonical):
            """Test Anthropic model name mappings."""
            pricing_variation = pricing_manager.get_pricing(model_variation, PROVIDER_ANTHROPIC)
            pricing_canonical = pricing_manager.get_pricing(canonical, PROVIDER_ANTHROPIC)
            
            assert pricing_variation.input_price == pricing_canonical.input_price
            assert pricing_variation.output_price == pricing_canonical.output_price
        
        def test_unknown_model_returns_zeros(self, pricing_manager):
            """Test that unknown models return zero pricing."""
            pricing = pricing_manager.get_pricing("unknown-model", PROVIDER_OPENAI)
            
            assert pricing.input_price == 0.0
            assert pricing.output_price == 0.0
            assert pricing.cache_price == 0.0
            assert pricing.reasoning_price == 0.0
        
        def test_unsupported_provider_raises_error(self, pricing_manager):
            """Test that unsupported providers raise ValueError."""
            with pytest.raises(ValueError, match="Unsupported provider 'unknown'"):
                pricing_manager.get_pricing("test-model", "unknown")
    
    class TestEndToEndIntegration:
        """Test end-to-end usage extraction and cost calculation."""
        
        def test_openai_end_to_end(self, pricing_manager):
            """Test complete OpenAI workflow."""
            # Create mock OpenAI response
            mock_usage = Mock()
            mock_usage.input_tokens = 1000
            mock_usage.output_tokens = 500
            
            mock_response = Mock()
            mock_response.id = "req_123"
            mock_response.usage = mock_usage
            
            usage, cost = pricing_manager.extract_usage_and_cost(
                mock_response, "gpt-5", PROVIDER_OPENAI
            )
            
            assert usage.input_tokens == 1000
            assert usage.output_tokens == 500
            assert usage.request_id == "req_123"
            
            # Expected cost: (1000/1M * 1.25) + (500/1M * 10.0) = 0.00125 + 0.005 = 0.00625
            expected_cost = 0.00625
            assert cost == pytest.approx(expected_cost, rel=1e-9)
        
        def test_anthropic_end_to_end(self, pricing_manager):
            """Test complete Anthropic workflow."""
            # Create mock Anthropic response
            mock_usage = Mock()
            mock_usage.input_tokens = 1000
            mock_usage.output_tokens = 500
            mock_usage.cache_read_input_tokens = 100
            mock_usage.cache_creation_input_tokens = 50
            
            mock_response = Mock()
            mock_response.id = "msg_123"
            mock_response.usage = mock_usage
            
            usage, cost = pricing_manager.extract_usage_and_cost(
                mock_response, "claude-sonnet-4", PROVIDER_ANTHROPIC
            )
            
            assert usage.input_tokens == 1000
            assert usage.output_tokens == 500
            assert usage.cache_tokens == 100
            assert usage.cache_write_tokens == 50
            assert usage.request_id == "msg_123"
            
            # Expected cost: (1000/1M * 3.0) + (500/1M * 15.0) + (100/1M * 0.3) + (50/1M * 3.75)
            # = 0.003 + 0.0075 + 0.00003 + 0.0001875 = 0.0107175
            expected_cost = 0.0107175
            assert cost == pytest.approx(expected_cost, rel=1e-9)
        
        def test_unknown_provider_extractor_error(self, pricing_manager):
            """Test error when no extractor is available for provider."""
            mock_response = Mock()
            
            with pytest.raises(ValueError, match="No extractor available for provider 'unknown'"):
                pricing_manager.extract_usage_and_cost(mock_response, "test-model", "unknown")
    
    class TestConfigurationLoading:
        """Test pricing configuration loading."""
        
        def test_load_config_from_file(self, mock_pricing_config):
            """Test loading configuration from file."""
            mock_file_content = '{"test": "data"}'
            
            with patch("builtins.open", mock_open(read_data=mock_file_content)):
                with patch("json.load") as mock_json_load:
                    mock_json_load.return_value = mock_pricing_config
                    
                    manager = ProviderPricingManager("/test/path")
                    
                    assert manager.pricing_config == mock_pricing_config
        
        def test_load_config_file_not_found(self):
            """Test handling when config file is not found."""
            with patch("builtins.open", side_effect=FileNotFoundError()):
                manager = ProviderPricingManager("/nonexistent/path")
                
                assert manager.pricing_config == {}
        
        def test_load_config_invalid_json(self):
            """Test handling when config file contains invalid JSON."""
            with patch("builtins.open", mock_open(read_data="invalid json")):
                with patch("json.load", side_effect=ValueError("Invalid JSON")):
                    manager = ProviderPricingManager("/test/path")
                    
                    assert manager.pricing_config == {}


class TestTokenTracker:
    """Test TokenTracker functionality."""
    
    @pytest.fixture
    def mock_pricing_config(self):
        """Mock pricing configuration for TokenTracker tests."""
        return {
            "openai": {
                "gpt-5": {
                    "input": 1.25,
                    "output": 10.0,
                    "cache_input": 0.125
                }
            },
            "anthropic": {
                "claude-sonnet-4": {
                    "input": 3.0,
                    "output": 15.0,
                    "cache_hits_and_refreshes": 0.3,
                    "cache_write": 3.75
                }
            }
        }
    
    @pytest.fixture
    def token_tracker(self, mock_pricing_config):
        """Create a TokenTracker with mocked pricing config."""
        with patch.object(ProviderPricingManager, '_load_pricing_config') as mock_load:
            mock_load.return_value = mock_pricing_config
            # Disable JSONL file writing for tests
            return TokenTracker(jsonl_path="")
    
    def test_record_openai_response(self, token_tracker):
        """Test recording an OpenAI response."""
        # Create mock OpenAI response
        mock_usage = Mock()
        mock_usage.input_tokens = 1000
        mock_usage.output_tokens = 500
        
        mock_response = Mock()
        mock_response.id = "req_123"
        mock_response.usage = mock_usage
        
        record = token_tracker.record_from_response(mock_response, "gpt-5", PROVIDER_OPENAI)
        
        assert record.model == "gpt-5"
        assert record.request_id == "req_123"
        assert record.input_tokens == 1000
        assert record.output_tokens == 500
        assert record.cache_tokens == 0
        assert record.cache_write_tokens == 0
        assert record.cost_usd > 0
        
        # Check that totals are updated
        totals = token_tracker.totals()
        assert totals["calls"] == 1
        assert totals["input_tokens"] == 1000
        assert totals["output_tokens"] == 500
    
    def test_record_anthropic_response(self, token_tracker):
        """Test recording an Anthropic response."""
        # Create mock Anthropic response
        mock_usage = Mock()
        mock_usage.input_tokens = 1000
        mock_usage.output_tokens = 500
        mock_usage.cache_read_input_tokens = 100
        mock_usage.cache_creation_input_tokens = 50
        
        mock_response = Mock()
        mock_response.id = "msg_123"
        mock_response.usage = mock_usage
        
        record = token_tracker.record_from_response(mock_response, "claude-sonnet-4", PROVIDER_ANTHROPIC)
        
        assert record.model == "claude-sonnet-4"
        assert record.request_id == "msg_123"
        assert record.input_tokens == 1000
        assert record.output_tokens == 500
        assert record.cache_tokens == 100
        assert record.cache_write_tokens == 50
        assert record.cost_usd > 0
    
    def test_multiple_records_accumulate(self, token_tracker):
        """Test that multiple records accumulate properly."""
        # Record first response
        mock_usage1 = Mock()
        mock_usage1.input_tokens = 500
        mock_usage1.output_tokens = 200
        
        mock_response1 = Mock()
        mock_response1.id = "req_1"
        mock_response1.usage = mock_usage1
        
        token_tracker.record_from_response(mock_response1, "gpt-5", PROVIDER_OPENAI)
        
        # Record second response
        mock_usage2 = Mock()
        mock_usage2.input_tokens = 800
        mock_usage2.output_tokens = 300
        
        mock_response2 = Mock()
        mock_response2.id = "req_2"
        mock_response2.usage = mock_usage2
        
        token_tracker.record_from_response(mock_response2, "gpt-5", PROVIDER_OPENAI)
        
        # Check totals
        totals = token_tracker.totals()
        assert totals["calls"] == 2
        assert totals["input_tokens"] == 1300  # 500 + 800
        assert totals["output_tokens"] == 500  # 200 + 300
        assert totals["cost_usd"] > 0
    
    def test_jsonl_writing_enabled(self, mock_pricing_config):
        """Test JSONL file writing when enabled."""
        with patch.object(ProviderPricingManager, '_load_pricing_config') as mock_load:
            mock_load.return_value = mock_pricing_config
            
            with patch("builtins.open", mock_open()) as mock_file:
                tracker = TokenTracker(jsonl_path="/test/path.jsonl")
                
                # Create mock response
                mock_usage = Mock()
                mock_usage.input_tokens = 1000
                mock_usage.output_tokens = 500
                
                mock_response = Mock()
                mock_response.id = "req_123"
                mock_response.usage = mock_usage
                
                tracker.record_from_response(mock_response, "gpt-5", PROVIDER_OPENAI)
                
                # Verify file was opened for append
                mock_file.assert_called_with("/test/path.jsonl", "a", encoding="utf-8")
                # Verify something was written
                handle = mock_file.return_value
                handle.write.assert_called()
    
    def test_jsonl_writing_error_handling(self, mock_pricing_config):
        """Test error handling when JSONL writing fails."""
        with patch.object(ProviderPricingManager, '_load_pricing_config') as mock_load:
            mock_load.return_value = mock_pricing_config
            
            with patch("builtins.open", side_effect=IOError("Permission denied")):
                tracker = TokenTracker(jsonl_path="/test/path.jsonl")
                
                # Create mock response
                mock_usage = Mock()
                mock_usage.input_tokens = 1000
                mock_usage.output_tokens = 500
                
                mock_response = Mock()
                mock_response.id = "req_123"
                mock_response.usage = mock_usage
                
                # Should not raise an exception despite file write error
                record = tracker.record_from_response(mock_response, "gpt-5", PROVIDER_OPENAI)
                
                # Record should still be created properly
                assert record.model == "gpt-5"
                assert record.input_tokens == 1000
    
    def test_totals_precision(self, token_tracker):
        """Test that cost totals maintain proper precision."""
        # Create response with small cost
        mock_usage = Mock()
        mock_usage.input_tokens = 1
        mock_usage.output_tokens = 1
        
        mock_response = Mock()
        mock_response.id = "req_123"
        mock_response.usage = mock_usage
        
        token_tracker.record_from_response(mock_response, "gpt-5", PROVIDER_OPENAI)
        
        totals = token_tracker.totals()
        
        # Cost should be rounded to 10 decimal places
        assert isinstance(totals["cost_usd"], float)
        # Very small cost, but should be > 0
        assert totals["cost_usd"] > 0
        assert totals["cost_usd"] < 0.001


class TestEdgeCasesAndErrorHandling:
    """Test edge cases and error handling scenarios."""
    
    def test_anthropic_model_mappings_completeness(self):
        """Test that ANTHROPIC_MODEL_MAPPINGS contains expected mappings."""
        expected_mappings = {
            "claude-opus-4-0": "claude-opus-4",
            "claude-sonnet-4-0": "claude-sonnet-4",
            "claude-3-7-sonnet-latest": "claude-sonnet-3-7",
            "claude-3-5-haiku-latest": "claude-haiku-3-5",
        }
        
        for model, expected_canonical in expected_mappings.items():
            assert model in ANTHROPIC_MODEL_MAPPINGS
            assert ANTHROPIC_MODEL_MAPPINGS[model] == expected_canonical
    
    def test_tokens_per_million_constant(self):
        """Test that TOKENS_PER_MILLION constant is correct."""
        assert TOKENS_PER_MILLION == 1_000_000.0
    
    @pytest.mark.parametrize("provider", [PROVIDER_OPENAI, PROVIDER_ANTHROPIC])
    def test_empty_response_handling(self, provider):
        """Test handling of completely empty responses."""
        extractor_class = OpenAIUsageExtractor if provider == PROVIDER_OPENAI else AnthropicUsageExtractor
        extractor = extractor_class()
        
        # Empty response object
        empty_response = Mock()
        # Remove usage attribute
        del empty_response.usage
        
        result = extractor.extract_usage(empty_response)
        
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.cache_tokens == 0
        assert result.cache_write_tokens == 0
        assert result.reasoning_tokens == 0
    
    def test_cost_calculation_precision(self):
        """Test that cost calculations maintain proper precision."""
        calculator = OpenAIPricingCalculator()
        
        # Very small usage
        usage = UsageMetrics(input_tokens=1, output_tokens=1)
        pricing = ProviderPricing(input_price=0.000001, output_price=0.000001)
        
        cost = calculator.calculate_cost(usage, pricing)
        
        # Should be able to handle very small costs without precision loss
        assert isinstance(cost, float)
        assert cost >= 0
    
    def test_dataclass_immutability(self):
        """Test that UsageMetrics and ProviderPricing are immutable."""
        usage = UsageMetrics(input_tokens=100)
        pricing = ProviderPricing(input_price=1.0)
        
        # Should not be able to modify frozen dataclasses
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            usage.input_tokens = 200
        
        with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
            pricing.input_price = 2.0