"""Token usage and pricing tracker for LangGraph multi-agent pipelines.

This module provides a pricing tracker specifically designed for LangGraph executions,
capturing token usage from both auxiliary LLMs (summarizer/collector) and reasoning LLMs
(worker agents). It tracks usage across parallel worker executions and aggregates costs
per model and overall.

Usage:
    from agent.multi.langgraph_pricing_tracker import LangGraphPricingTracker

    tracker = LangGraphPricingTracker()

    # Wrap LLMs with tracking callbacks
    auxiliary_llm = tracker.wrap_llm(ChatOpenAI(model="gpt-5-nano"), "auxiliary")
    reasoning_llm = tracker.wrap_llm(ChatOpenAI(model="gpt-5.1"), "reasoning")

    # Run your pipeline...

    # Get pricing summary
    summary = tracker.get_summary()
    tracker.save_to_file("langgraph_pricing.json")
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from utils.logger import logger
from utils.token_costs import compute_cost_usd, get_pricing_for_model, load_pricing


@dataclass
class LLMCallRecord:
    """Record of a single LLM call in the LangGraph execution.

    Attributes:
        timestamp: ISO timestamp when the call was made
        model: Model name used for the call
        role: Role of the LLM ("auxiliary" for summarizer/collector, "reasoning" for workers)
        worker_id: Optional worker identifier for parallel executions
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        cache_input_tokens: Number of cached input tokens
        cost_usd: Cost in USD for this call
    """

    timestamp: str
    model: str
    role: str  # "auxiliary" or "reasoning"
    worker_id: Optional[str]
    input_tokens: int
    output_tokens: int
    cache_input_tokens: int
    cost_usd: float


@dataclass
class ModelSummary:
    """Aggregated statistics for a specific model.

    Attributes:
        model: Model name
        call_count: Number of calls to this model
        total_input_tokens: Sum of input tokens across all calls
        total_output_tokens: Sum of output tokens across all calls
        total_cache_input_tokens: Sum of cached input tokens across all calls
        total_cost_usd: Total cost in USD across all calls
    """

    model: str
    call_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_cache_input_tokens: int
    total_cost_usd: float


@dataclass
class PipelineSummary:
    """Complete summary of LangGraph pipeline execution costs.

    Attributes:
        start_time: ISO timestamp when tracking started
        end_time: ISO timestamp when summary was generated
        total_calls: Total number of LLM calls across all models
        total_input_tokens: Sum of all input tokens
        total_output_tokens: Sum of all output tokens
        total_cache_input_tokens: Sum of all cached input tokens
        total_cost_usd: Total cost in USD for entire pipeline
        by_model: Per-model breakdown of usage and costs
        by_role: Per-role breakdown (auxiliary vs reasoning)
        worker_count: Number of parallel workers executed
    """

    start_time: str
    end_time: str
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cache_input_tokens: int
    total_cost_usd: float
    by_model: Dict[str, ModelSummary]
    by_role: Dict[str, Dict[str, Any]]
    worker_count: int


class LangGraphCallbackHandler(BaseCallbackHandler):
    """Callback handler to capture token usage from LangChain/LangGraph LLM calls."""

    def __init__(
        self,
        tracker: LangGraphPricingTracker,
        role: str,
        worker_id: Optional[str] = None,
    ):
        """Initialize callback handler.

        Args:
            tracker: Parent pricing tracker instance
            role: Role of this LLM ("auxiliary" or "reasoning")
            worker_id: Optional identifier for parallel worker executions
        """
        super().__init__()
        self.tracker = tracker
        self.role = role
        self.worker_id = worker_id

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """Called when LLM completes. Extracts token usage and records it.

        Args:
            response: LLMResult containing generations and usage metadata
            **kwargs: Additional callback arguments
        """
        if not response.generations:
            return

        # Extract usage information from LLMResult
        llm_output = response.llm_output or {}
        usage = llm_output.get("token_usage", {})

        # Extract token counts with fallback to 0
        input_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0) or usage.get(
            "output_tokens", 0
        )

        # Cache tokens might be in different locations
        cache_input_tokens = 0
        if "cached_tokens" in usage:
            cache_input_tokens = usage["cached_tokens"]
        elif "prompt_tokens_details" in usage:
            details = usage["prompt_tokens_details"]
            cache_input_tokens = details.get("cached_tokens", 0)

        # Get model name
        model = llm_output.get("model_name", "unknown")

        # Record the usage
        self.tracker.record_call(
            model=model,
            role=self.role,
            worker_id=self.worker_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_input_tokens=cache_input_tokens,
        )


class LangGraphPricingTracker:
    """Tracks token usage and costs for LangGraph multi-agent pipeline executions.

    This tracker wraps LLMs with callback handlers to automatically capture token usage
    from all LLM calls in the pipeline, including parallel worker executions.
    """

    def __init__(self, pricing_path: Optional[str] = None):
        """Initialize the pricing tracker.

        Args:
            pricing_path: Optional path to custom pricing JSON file.
                         If None, uses default from utils/token_pricing.json
        """
        self._pricing_map = load_pricing(pricing_path)
        self._records: List[LLMCallRecord] = []
        self._start_time = datetime.now(timezone.utc).isoformat()
        self._worker_counter = 0

        logger.info("LangGraph pricing tracker initialized")

    def wrap_llm(self, llm: Any, role: str, worker_id: Optional[str] = None) -> Any:
        """Wrap an LLM with usage tracking callbacks.

        Args:
            llm: LangChain LLM instance to wrap
            role: Role of this LLM ("auxiliary" for summarizer/collector,
                  "reasoning" for worker agents)
            worker_id: Optional worker identifier for parallel executions.
                      If None and role is "reasoning", auto-generates worker IDs.

        Returns:
            LLM instance configured with tracking callbacks
        """
        # Auto-generate worker ID for reasoning LLMs if not provided
        if role == "reasoning" and worker_id is None:
            self._worker_counter += 1
            worker_id = f"worker_{self._worker_counter}"

        callback = LangGraphCallbackHandler(self, role, worker_id)

        # Add callback to LLM's callbacks
        if hasattr(llm, "callbacks"):
            if llm.callbacks is None:
                llm.callbacks = []
            llm.callbacks.append(callback)
        else:
            llm.callbacks = [callback]

        logger.debug(f"Wrapped LLM with tracking: role={role}, worker_id={worker_id}")
        return llm

    def record_call(
        self,
        model: str,
        role: str,
        worker_id: Optional[str],
        input_tokens: int,
        output_tokens: int,
        cache_input_tokens: int,
    ) -> LLMCallRecord:
        """Record a single LLM call with token usage.

        Args:
            model: Model name
            role: Role of the LLM ("auxiliary" or "reasoning")
            worker_id: Optional worker identifier
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            cache_input_tokens: Number of cached input tokens

        Returns:
            LLMCallRecord with usage and cost information
        """
        # Get pricing for the model
        pricing = get_pricing_for_model(model, pricing_map=self._pricing_map, warn=True)

        # Calculate cost
        cost = compute_cost_usd(
            pricing,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_input_tokens=cache_input_tokens,
        )

        # Create record
        record = LLMCallRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            model=model,
            role=role,
            worker_id=worker_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_input_tokens=cache_input_tokens,
            cost_usd=round(cost, 10),
        )

        self._records.append(record)

        # Log the call
        worker_info = f" worker={worker_id}" if worker_id else ""
        logger.info(
            f"LangGraph call | role={role}{worker_info} model={model} "
            f"in={input_tokens} out={output_tokens} cache={cache_input_tokens} "
            f"cost=${cost:.6f}"
        )

        return record

    def get_summary(self) -> PipelineSummary:
        """Generate comprehensive summary of pipeline execution costs.

        Returns:
            PipelineSummary with aggregated statistics by model, role, and overall
        """
        if not self._records:
            logger.warning("No LLM calls recorded. Summary will be empty.")
            return PipelineSummary(
                start_time=self._start_time,
                end_time=datetime.now(timezone.utc).isoformat(),
                total_calls=0,
                total_input_tokens=0,
                total_output_tokens=0,
                total_cache_input_tokens=0,
                total_cost_usd=0.0,
                by_model={},
                by_role={},
                worker_count=0,
            )

        # Aggregate by model
        by_model: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "call_count": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cache_input_tokens": 0,
                "total_cost_usd": 0.0,
            }
        )

        # Aggregate by role
        by_role: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "call_count": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_cache_input_tokens": 0,
                "total_cost_usd": 0.0,
            }
        )

        # Track unique workers
        unique_workers = set()

        # Process all records
        total_input = 0
        total_output = 0
        total_cache = 0
        total_cost = 0.0

        for record in self._records:
            # Update model stats
            by_model[record.model]["call_count"] += 1
            by_model[record.model]["total_input_tokens"] += record.input_tokens
            by_model[record.model]["total_output_tokens"] += record.output_tokens
            by_model[record.model][
                "total_cache_input_tokens"
            ] += record.cache_input_tokens
            by_model[record.model]["total_cost_usd"] += record.cost_usd

            # Update role stats
            by_role[record.role]["call_count"] += 1
            by_role[record.role]["total_input_tokens"] += record.input_tokens
            by_role[record.role]["total_output_tokens"] += record.output_tokens
            by_role[record.role][
                "total_cache_input_tokens"
            ] += record.cache_input_tokens
            by_role[record.role]["total_cost_usd"] += record.cost_usd

            # Track workers
            if record.worker_id:
                unique_workers.add(record.worker_id)

            # Update totals
            total_input += record.input_tokens
            total_output += record.output_tokens
            total_cache += record.cache_input_tokens
            total_cost += record.cost_usd

        # Convert by_model dict to ModelSummary objects
        model_summaries = {
            model: ModelSummary(
                model=model,
                call_count=stats["call_count"],
                total_input_tokens=stats["total_input_tokens"],
                total_output_tokens=stats["total_output_tokens"],
                total_cache_input_tokens=stats["total_cache_input_tokens"],
                total_cost_usd=round(stats["total_cost_usd"], 10),
            )
            for model, stats in by_model.items()
        }

        # Round role costs
        for role_stats in by_role.values():
            role_stats["total_cost_usd"] = round(role_stats["total_cost_usd"], 10)

        return PipelineSummary(
            start_time=self._start_time,
            end_time=datetime.now(timezone.utc).isoformat(),
            total_calls=len(self._records),
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_cache_input_tokens=total_cache,
            total_cost_usd=round(total_cost, 10),
            by_model=model_summaries,
            by_role=dict(by_role),
            worker_count=len(unique_workers),
        )

    def save_to_file(self, filepath: str) -> None:
        """Save detailed pricing data and summary to JSON file.

        Args:
            filepath: Path to save JSON file (e.g., "langgraph_pricing.json")
        """
        summary = self.get_summary()

        # Convert to serializable format
        output = {
            "summary": {
                "start_time": summary.start_time,
                "end_time": summary.end_time,
                "total_calls": summary.total_calls,
                "total_input_tokens": summary.total_input_tokens,
                "total_output_tokens": summary.total_output_tokens,
                "total_cache_input_tokens": summary.total_cache_input_tokens,
                "total_cost_usd": summary.total_cost_usd,
                "worker_count": summary.worker_count,
                "by_model": {
                    model: asdict(stats) for model, stats in summary.by_model.items()
                },
                "by_role": summary.by_role,
            },
            "detailed_calls": [asdict(record) for record in self._records],
        }

        # Write to file
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        logger.info(f"Pricing data saved to {filepath}")
        logger.info(
            f"Total cost: ${summary.total_cost_usd:.6f} across {summary.total_calls} calls"
        )

    def log_summary(self) -> None:
        """Log a formatted summary of pricing data to the logger."""
        summary = self.get_summary()

        logger.info("=" * 60)
        logger.info("LangGraph Pipeline Pricing Summary")
        logger.info("=" * 60)
        logger.info(f"Total Calls: {summary.total_calls}")
        logger.info(f"Total Cost: ${summary.total_cost_usd:.6f}")
        logger.info(f"Workers: {summary.worker_count}")
        logger.info("")
        logger.info("Token Usage:")
        logger.info(f"  Input: {summary.total_input_tokens:,}")
        logger.info(f"  Output: {summary.total_output_tokens:,}")
        logger.info(f"  Cached: {summary.total_cache_input_tokens:,}")
        logger.info("")
        logger.info("By Model:")
        for model, stats in summary.by_model.items():
            logger.info(f"  {model}:")
            logger.info(f"    Calls: {stats.call_count}")
            logger.info(f"    Cost: ${stats.total_cost_usd:.6f}")
        logger.info("")
        logger.info("By Role:")
        for role, stats in summary.by_role.items():
            logger.info(f"  {role}:")
            logger.info(f"    Calls: {stats['call_count']}")
            logger.info(f"    Cost: ${stats['total_cost_usd']:.6f}")
        logger.info("=" * 60)
