"""Token-aware output truncation for Kali command outputs.

This module provides intelligent truncation of command outputs to fit within
token limits while preserving the most important parts (beginning and end)
and ensuring complete logs are maintained for debugging purposes.

The truncator uses the existing TokenTracker infrastructure and follows
best practices for class-based design.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from utils.logger import logger

@dataclass
class TruncationResult:
    """Result of output truncation operation.
    
    Attributes:
        truncated_output: The truncated version for model consumption
        was_truncated: Whether truncation was performed
        original_tokens: Number of tokens in original output
        final_tokens: Number of tokens in truncated output (includes markers)
        content_tokens_kept: Number of original content tokens kept (excludes markers)
        tokens_removed_from_original: Number of original content tokens removed
        truncation_method: Method used for truncation
        removed_middle_token_span: Tuple of (start_token_idx, end_token_idx) for removed middle section
        metadata: Additional truncation metadata
    """
    truncated_output: str
    was_truncated: bool
    original_tokens: int
    final_tokens: int
    content_tokens_kept: int
    tokens_removed_from_original: int
    truncation_method: str
    removed_middle_token_span: Optional[Tuple[int, int]]
    metadata: Dict[str, Any]


class TokenTruncator:
    """Intelligent token-aware output truncator.
    
    This class provides functionality to truncate command outputs while
    preserving the most important parts and maintaining complete logs.
    Thread-safe after initialization.
    """
    
    def __init__(
        self, 
        model: str, 
        max_tokens: int,
        encoding: Optional[Any] = None
    ):
        """Initialize the token truncator.
        
        Args:
            model: Model name for token counting (e.g., "gpt-5-2025-08-07")
            max_tokens: Maximum number of tokens allowed in output
            encoding: Optional encoding to use (for testing). If None, auto-detect from model.
        """
        self.model = model
        self.max_tokens = max_tokens
        
        # Initialize tokenizer encoding
        self._encoding = encoding if encoding is not None else self._get_encoding()
        
        logger.debug(f"TokenTruncator initialized for model '{model}' max_tokens={max_tokens}")
    
    def _get_encoding(self):
        """Get the appropriate tiktoken encoding for the model.
        
        Returns:
            tiktoken encoding object
            
        Raises:
            ImportError: If tiktoken is not available
            ValueError: If model encoding cannot be determined
        """
        try:
            import tiktoken
        except ImportError:
            logger.error("tiktoken not available. Install with: pip install tiktoken")
            raise ImportError("tiktoken is required for token counting")
        
        try:
            # Try model-aware encoding first (preferred method)
            return tiktoken.encoding_for_model(self.model)
        except KeyError:
            # Fall back to manual encoding selection
            encoding_name = self._get_model_encoding_name()
            return tiktoken.get_encoding(encoding_name)
    
    def _get_model_encoding_name(self) -> str:
        """Get the tiktoken encoding name for the model.
        
        Returns:
            tiktoken encoding name (e.g., "cl100k_base", "o200k_base")
        """
        # Strip date suffix if present
        base_model = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", self.model)
        
        # Map model families to their encodings
        # GPT-5 uses o200k_base encoding (not cl100k_base like GPT-4)
        encoding_map = {
            "gpt-5": "o200k_base",  # GPT-5 uses o200k_base encoding
            "gpt-4": "cl100k_base",
            "gpt-3.5": "cl100k_base", 
            "o3": "o200k_base",  # o3 uses o200k_base
            "o1": "o200k_base",
        }
        
        # Try exact match first
        if base_model in encoding_map:
            return encoding_map[base_model]
        
        # Try partial matches
        for model_family, encoding in encoding_map.items():
            if base_model.startswith(model_family):
                return encoding
        
        # Default fallback - use o200k_base for modern models
        logger.warning(f"Unknown model '{self.model}', using o200k_base as fallback")
        return "o200k_base"
    
    def _encode(self, text: str) -> list:
        """Encode text to tokens. Fails fast on errors.
        
        Args:
            text: Text to encode
            
        Returns:
            List of token IDs
            
        Raises:
            Exception: If encoding fails
        """
        if not text:
            return []
        return self._encoding.encode(text)
    
    def _decode(self, tokens: list) -> str:
        """Decode tokens to text. Fails fast on errors.
        
        Args:
            tokens: List of token IDs
            
        Returns:
            Decoded text
            
        Raises:
            Exception: If decoding fails
        """
        if not tokens:
            return ""
        return self._encoding.decode(tokens)
    
    def count_tokens(self, text: str) -> int:
        """Count tokens in text using the model's tokenizer.
        
        Args:
            text: Text to count tokens for
            
        Returns:
            Number of tokens in the text
        """
        return len(self._encode(text))
    
    def truncate_output(self, output: str, budget: Optional[int] = None) -> TruncationResult:
        """Intelligently truncate output to fit within token limit.
        
        This method preserves the beginning and end of the output while removing
        only the middle portion necessary to fit within the token limit.
        
        Args:
            output: The full output text to potentially truncate
            budget: Override max_tokens for this call (useful when budget is dynamic)
            
        Returns:
            TruncationResult with truncated output and metadata
        """
        if not output:
            return TruncationResult(
                truncated_output=output,
                was_truncated=False,
                original_tokens=0,
                final_tokens=0,
                content_tokens_kept=0,
                tokens_removed_from_original=0,
                truncation_method="none",
                removed_middle_token_span=None,
                metadata={}
            )
        
        # Use provided budget or default max_tokens
        token_budget = budget if budget is not None else self.max_tokens
        
        # Encode once and reuse tokens
        tokens = self._encode(output)
        original_tokens = len(tokens)
        
        # If output fits within limit, return as-is
        if original_tokens <= token_budget:
            return TruncationResult(
                truncated_output=output,
                was_truncated=False,
                original_tokens=original_tokens,
                final_tokens=original_tokens,
                content_tokens_kept=original_tokens,
                tokens_removed_from_original=0,
                truncation_method="none",
                removed_middle_token_span=None,
                metadata={}
            )
            
        truncated_output, content_tokens_kept, removed_span, truncation_method = self._truncate_simple(
            tokens, token_budget
        )
        
        # Count final tokens
        final_tokens = len(self._encode(truncated_output))
        tokens_removed_from_original = original_tokens - content_tokens_kept
        
        # Determine if truncation actually occurred
        was_truncated = (content_tokens_kept < original_tokens) or (final_tokens != original_tokens)
        
        result = TruncationResult(
            truncated_output=truncated_output,
            was_truncated=was_truncated,
            original_tokens=original_tokens,
            final_tokens=final_tokens,
            content_tokens_kept=content_tokens_kept,
            tokens_removed_from_original=tokens_removed_from_original,
            truncation_method=truncation_method,
            removed_middle_token_span=removed_span,
            metadata={
                "token_budget": token_budget,
                "marker_tokens": final_tokens - content_tokens_kept
            }
        )
        
        logger.debug(
            f"Output truncated: {original_tokens} -> {final_tokens} tokens "
            f"(kept {content_tokens_kept} content tokens, removed {tokens_removed_from_original})"
        )
        
        return result
    
    def _truncate_simple(
        self, 
        tokens: list, 
        token_budget: int
    ) -> Tuple[str, int, Tuple[int, int], str]:
        """Simple truncation that only removes what's necessary to fit the budget.
        
        Uses binary search for O(log N) performance instead of O(N).
        
        Args:
            tokens: Encoded tokens
            token_budget: Maximum allowed tokens
            
        Returns:
            Tuple of (truncated_text, content_tokens_kept, removed_span, truncation_method)
        """
        total_tokens = len(tokens)
        
        # Cache marker token count for performance
        marker_text = f"\n\n[TRUNCATED - X tokens removed]\n\n"
        marker_tokens = self._encode(marker_text)
        marker_token_count = len(marker_tokens)
        
        # Binary search for optimal head_tokens
        left, right = 1, total_tokens // 2
        best_result = None
        
        while left <= right:
            mid = (left + right) // 2
            head_tokens = mid
            tail_tokens = min(head_tokens, total_tokens - head_tokens)
            
            # Check if this fits
            total_needed = head_tokens + tail_tokens + marker_token_count
            if total_needed <= token_budget:
                # This fits, try to find a better (larger) solution
                best_result = (head_tokens, tail_tokens)
                left = mid + 1
            else:
                # This doesn't fit, try smaller
                right = mid - 1
        
        if best_result:
            head_tokens, tail_tokens = best_result
            
            # Calculate actual removed tokens for marker
            actual_removed_tokens = total_tokens - head_tokens - tail_tokens
            marker_text = f"\n\n[TRUNCATED - {actual_removed_tokens} tokens removed]\n\n"
            
            # Get the preserved tokens
            start_tokens = tokens[:head_tokens]
            end_tokens = tokens[-tail_tokens:]
            
            # Decode the preserved tokens
            start_text = self._decode(start_tokens)
            end_text = self._decode(end_tokens)
            
            # Combine with truncation marker
            truncated_text = f"{start_text}{marker_text}{end_text}"
            
            # CRITICAL: Check for marker overrun and handle it properly
            final_tokens = len(self._encode(truncated_text))
            if final_tokens > token_budget:
                # Marker overrun! Trim tokens proportionally from both ends
                overrun = final_tokens - token_budget
                
                # Trim proportionally from head and tail
                head_trim = (overrun * head_tokens) // (head_tokens + tail_tokens)
                tail_trim = overrun - head_trim
                
                # Ensure we don't trim more than available
                head_trim = min(head_trim, head_tokens - 1)  # Keep at least 1 token
                tail_trim = min(tail_trim, tail_tokens - 1)  # Keep at least 1 token
                
                # Recalculate with trimmed amounts
                head_tokens -= head_trim
                tail_tokens -= tail_trim
                actual_removed_tokens = total_tokens - head_tokens - tail_tokens
                
                # Rebuild with corrected amounts
                marker_text = f"\n\n[TRUNCATED - {actual_removed_tokens} tokens removed]\n\n"
                start_tokens = tokens[:head_tokens]
                end_tokens = tokens[-tail_tokens:]
                start_text = self._decode(start_tokens)
                end_text = self._decode(end_tokens)
                truncated_text = f"{start_text}{marker_text}{end_text}"
            
            # Calculate removed span
            removed_start = head_tokens
            removed_end = total_tokens - tail_tokens
            
            return truncated_text, head_tokens + tail_tokens, (removed_start, removed_end), "head_tail"
        
        # Fallback: head-only mode
        return self._truncate_head_only(tokens, token_budget)
    
    def _truncate_head_only(
        self, 
        tokens: list, 
        token_budget: int
    ) -> Tuple[str, int, Tuple[int, int], str]:
        """Fallback to head-only mode when budget is too small for head-tail.
        
        Args:
            tokens: Encoded tokens
            token_budget: Maximum allowed tokens
            
        Returns:
            Tuple of (truncated_text, content_tokens_kept, removed_span, truncation_method)
        """
        total_tokens = len(tokens)
        
        # Try different marker sizes
        markers = ["[TRUNCATED]", "[...]", ""]
        
        for marker in markers:
            marker_tokens = self._encode(marker)
            marker_token_count = len(marker_tokens)
            
            if marker_token_count > token_budget:
                continue
            
            content_budget = token_budget - marker_token_count
            
            if content_budget <= 0:
                # Only marker fits
                return marker, 0, (0, total_tokens), "marker_only"
            
            # Take only from the beginning
            head_tokens = tokens[:content_budget]
            head_text = self._decode(head_tokens)
            truncated_text = f"{head_text}{marker}"
            
            # Verify it fits
            final_tokens = self._encode(truncated_text)
            if len(final_tokens) <= token_budget:
                removed_span = (content_budget, total_tokens)
                return truncated_text, content_budget, removed_span, "head_only"
        
        # Last resort: empty string
        return "", 0, (0, total_tokens), "empty"
    
    def get_summary(self, result: TruncationResult) -> str:
        """Generate a summary of truncation result.
        
        Args:
            result: TruncationResult from truncate_output
            
        Returns:
           summary string
        """
        if not result.was_truncated:
            return f"Output not truncated ({result.original_tokens} tokens)"
        
        summary = (
            f"Output truncated: {result.original_tokens} -> "
            f"{result.final_tokens} tokens "
            f"(kept {result.content_tokens_kept} content tokens, "
            f"removed {result.tokens_removed_from_original} from original, "
            f"method: {result.truncation_method})"
        )
        
        if result.removed_middle_token_span:
            start, end = result.removed_middle_token_span
            summary += f", removed span: tokens {start}-{end}"
        
        return summary
