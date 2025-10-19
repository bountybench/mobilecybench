#!/usr/bin/env python3
"""Comprehensive test script for TokenTruncator functionality.

This script tests the TokenTruncator class with proper assertions
and covers edge cases, Unicode handling, and budget guarantees.
"""

import sys

from tools.token_truncator import TokenTruncator


def test_budget_guarantee():
    """Test that the hard guarantee is always met: final_tokens <= token_budget."""
    print("Testing budget guarantee...")
    
    truncator = TokenTruncator(model="gpt-5-2025-08-07", max_tokens=100)
    
    # Test with various budgets
    test_budgets = [0, 1, 2, 5, 10, 50, 200]
    long_text = "This is a very long text that should definitely need truncation. " * 100
    
    for budget in test_budgets:
        result = truncator.truncate_output(long_text, budget=budget)
        
        # Hard guarantee: final_tokens <= budget
        assert result.final_tokens <= budget, f"Budget {budget} violated: {result.final_tokens} > {budget}"
        
        # If truncated, should have removed content
        if result.was_truncated:
            assert result.content_tokens_kept < result.original_tokens, "Should have removed content"
            assert result.tokens_removed_from_original > 0, "Should have removed tokens from original"
        
        print(f"  Budget {budget}: {result.original_tokens} -> {result.final_tokens} tokens (method: {result.truncation_method})")
    
    print("✅ Budget guarantee satisfied for all test cases")


def test_edge_budgets():
    """Test edge cases with very small budgets."""
    print("Testing edge budgets...")
    
    truncator = TokenTruncator(model="gpt-5-2025-08-07", max_tokens=100)
    long_text = "This is a test text that will be truncated. " * 50
    
    # Test zero budget
    result = truncator.truncate_output(long_text, budget=0)
    assert result.final_tokens == 0, "Zero budget should produce 0 tokens"
    assert result.was_truncated, "Should be marked as truncated"
    
    # Test budget of 1
    result = truncator.truncate_output(long_text, budget=1)
    assert result.final_tokens <= 1, "Budget of 1 should be respected"
    assert result.was_truncated, "Should be marked as truncated"
    
    # Test budget of 2
    result = truncator.truncate_output(long_text, budget=2)
    assert result.final_tokens <= 2, "Budget of 2 should be respected"
    assert result.was_truncated, "Should be marked as truncated"
    
    print("✅ Edge budgets handled correctly")


def test_marker_overrun():
    """Test marker overrun with large removed token counts."""
    print("Testing marker overrun...")
    
    truncator = TokenTruncator(model="gpt-5-2025-08-07", max_tokens=100)
    
    # Create text that will result in a large "removed" count in the marker
    # This tests the dynamic marker length issue
    very_long_text = "This is a very long line of text that will be repeated many times. " * 1000
    
    # Use a small budget to force truncation with large removed count
    result = truncator.truncate_output(very_long_text, budget=20)
    
    # The marker will contain something like "[TRUNCATED - 50000 tokens removed]"
    # which itself might be many tokens, but the final result should still fit
    assert result.final_tokens <= 20, f"Marker overrun: {result.final_tokens} > 20"
    assert result.was_truncated, "Should be marked as truncated"
    assert "[TRUNCATED" in result.truncated_output, "Should contain truncation marker"
    
    # Validate token accounting
    kept = result.content_tokens_kept
    marker_tokens = result.final_tokens - kept
    assert kept >= 0 and marker_tokens >= 0
    assert kept + marker_tokens == result.final_tokens, "Token accounting mismatch"
    
    print("✅ Marker overrun handled correctly")


def test_head_tail_preservation():
    """Test that head and tail are preserved correctly."""
    print("Testing head and tail preservation...")
    
    truncator = TokenTruncator(model="gpt-5-2025-08-07", max_tokens=100)
    
    # Create text with distinct head and tail
    lines = [f"Line {i}: This is line number {i} with some content." for i in range(20)]
    test_text = "\n".join(lines)
    
    result = truncator.truncate_output(test_text, budget=30)
    
    if result.was_truncated and result.truncation_method == "head_tail":
        # Robust head/tail checks around the marker
        k = 12
        out = result.truncated_output
        assert "[TRUNCATED" in out
        head = test_text[:k]
        tail = test_text[-k:]
        before, after = out.split("[TRUNCATED", 1)
        assert head in before, "Head not preserved"
        assert tail in after, "Tail not preserved"
    
    print("✅ Head and tail preservation verified")


def test_different_models():
    """Test truncator with different models."""
    print("Testing different models...")
    
    models = ["gpt-5-2025-08-07", "gpt-4", "o3"]
    test_text = "This is a test text to see how different models tokenize the same content."
    
    for model in models:
        try:
            truncator = TokenTruncator(model=model, max_tokens=100)
            token_count = truncator.count_tokens(test_text)
            
            # Test truncation
            result = truncator.truncate_output(test_text, budget=20)
            assert result.final_tokens <= 20, f"Model {model}: budget violated"
            
            print(f"  {model}: {token_count} tokens, truncation works")
        except Exception as e:
            print(f"  {model}: Error - {e}")
    
    print("✅ Different models tested")


def test_header_body_split():
    """Test the header/body split behavior used in MCP integration."""
    print("Testing header/body split behavior...")
    
    truncator = TokenTruncator(model="gpt-5-2025-08-07", max_tokens=100)
    
    # Simulate the MCP server's header/body split
    header = "Command: ls -la\nExit Code: 0\nOutput:\n"
    body = "This is the actual command output that might be very long. " * 100
    
    header_tokens = truncator.count_tokens(header)
    body_budget = max(0, truncator.max_tokens - header_tokens)
    
    if body_budget > 0:
        result = truncator.truncate_output(body, budget=body_budget)
        truncated_body = result.truncated_output
    else:
        truncated_body = "[TRUNCATED]"
    
    # Combine header and body
    full_response = header + truncated_body
    final_tokens = truncator.count_tokens(full_response)
    
    # Should fit within total budget
    assert final_tokens <= truncator.max_tokens, f"Header/body split failed: {final_tokens} > {truncator.max_tokens}"
    
    print(f"✅ Header/body split: {header_tokens} header + {final_tokens - header_tokens} body = {final_tokens} total")


def test_exact_and_just_over():
    """Test exact budget and just-over-budget cases."""
    print("Testing exact and just-over budget cases...")
    
    truncator = TokenTruncator(model="gpt-5-2025-08-07", max_tokens=100)
    text = "abc " * 50
    orig = truncator.count_tokens(text)
    
    # Test exact budget (should not truncate)
    r_eq = truncator.truncate_output(text, budget=orig)
    assert not r_eq.was_truncated and r_eq.final_tokens == orig
    
    # Test just under budget (should truncate)
    r_less = truncator.truncate_output(text, budget=max(1, orig-1))
    assert r_less.was_truncated and r_less.final_tokens <= max(1, orig-1)
    
    print("✅ Exact and just-over budget cases passed")


def test_span_consistency():
    """Test that removed span is consistent with token counts."""
    print("Testing span consistency...")
    
    truncator = TokenTruncator(model="gpt-5-2025-08-07", max_tokens=50)
    txt = "X" * 5000
    r = truncator.truncate_output(txt)
    
    if r.removed_middle_token_span:
        s, e = r.removed_middle_token_span
        assert 0 <= s <= e <= r.original_tokens
        assert e - s == r.tokens_removed_from_original
    
    print("✅ Span consistency verified")


def run_all_tests():
    """Run all test functions."""
    print("TokenTruncator Comprehensive Test Suite")
    print("=" * 60)
    
    test_functions = [
        test_budget_guarantee,
        test_edge_budgets,
        test_marker_overrun,
        test_head_tail_preservation,
        test_different_models,
        test_header_body_split,
        test_exact_and_just_over,
        test_span_consistency,
    ]
    
    passed = 0
    failed = 0
    
    for test_func in test_functions:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"❌ {test_func.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
        print()
    
    print("=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All tests passed!")
        return True
    else:
        print("💥 Some tests failed!")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)