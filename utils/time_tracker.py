"""
Time tracking utility for MobileCybench experiments.

Tracks:
- Total experiment clock time (from runner.py start to completion)
- Individual LLM call times with context manager for exception safety
- Total LLM time across all calls
- Structured JSON output for CI/analysis
"""

import json
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Constants
LOG_SEPARATOR_LENGTH = 60


@dataclass
class LLMCallTiming:
    """Timing data for a single LLM call."""

    call_id: str
    call_number: int
    start_time: float
    end_time: float
    duration: float
    model: str
    conversation_id: Optional[str] = None
    turn: Optional[int] = None
    success: bool = True
    error: Optional[str] = None


@dataclass
class ExperimentTiming:
    """Complete experiment timing data."""

    experiment_id: str
    app_name: str
    start_time: float
    end_time: float
    total_duration: float
    llm_calls: List[LLMCallTiming]
    total_llm_time: float
    llm_call_count: int
    stats: Dict[str, Any]


class TimeTracker:
    """Tracks timing for MobileCybench experiments with context manager support."""

    def __init__(self):
        self.experiment_start_time: Optional[float] = None
        self.experiment_end_time: Optional[float] = None
        self.llm_calls: List[LLMCallTiming] = []
        self._current_call_number = 0
        self._experiment_id: Optional[str] = None
        self._app_name: Optional[str] = None
        self._call_counter = 0  # For unique call IDs

    def start_experiment(self, app_name: str = None) -> None:
        """Mark the start of the experiment."""
        self.experiment_start_time = time.perf_counter()
        self._experiment_id = f"exp_{int(time.time())}"
        self._app_name = app_name or "unknown"

    def end_experiment(self) -> None:
        """Mark the end of the experiment."""
        self.experiment_end_time = time.perf_counter()

    @contextmanager
    def llm_timing(
        self,
        model: str,
        conversation_id: Optional[str] = None,
        turn: Optional[int] = None,
    ):
        """Context manager for LLM call timing with automatic exception handling."""
        self._current_call_number += 1
        self._call_counter += 1
        call_id = (
            f"call_{self._current_call_number}_{self._call_counter}_{int(time.time())}"
        )

        call_timing = LLMCallTiming(
            call_id=call_id,
            call_number=self._current_call_number,
            start_time=time.perf_counter(),
            end_time=0.0,
            duration=0.0,
            model=model,
            conversation_id=conversation_id,
            turn=turn,
            success=True,
            error=None,
        )
        self.llm_calls.append(call_timing)

        try:
            yield call_timing
        except Exception as e:
            # Error case - mark as failed
            call_timing.success = False
            call_timing.error = str(e)
            raise
        finally:
            # Always set end time and duration, regardless of success/failure
            call_timing.end_time = time.perf_counter()
            call_timing.duration = call_timing.end_time - call_timing.start_time

    def get_experiment_duration(self) -> Optional[float]:
        """Get total experiment duration in seconds."""
        if self.experiment_start_time and self.experiment_end_time:
            return self.experiment_end_time - self.experiment_start_time
        return None

    def get_total_llm_time(self) -> float:
        """Get total time spent on LLM calls in seconds."""
        return sum(call.duration for call in self.llm_calls)

    def get_llm_call_count(self) -> int:
        """Get total number of LLM calls made."""
        return len(self.llm_calls)

    def _compute_stats(self) -> Dict[str, Any]:
        """Compute timing statistics."""
        if not self.llm_calls:
            return {}

        durations = [call.duration for call in self.llm_calls]
        durations.sort()

        n = len(durations)
        stats = {
            "overall": {
                "count": n,
                "total": sum(durations),
                "min": min(durations),
                "max": max(durations),
                "mean": sum(durations) / n,
                "p50": durations[n // 2],
                "p95": durations[int(n * 0.95)] if n > 1 else durations[0],
                "p99": durations[int(n * 0.99)] if n > 1 else durations[0],
            }
        }

        # Per-model stats
        model_stats = {}
        for call in self.llm_calls:
            if call.model not in model_stats:
                model_stats[call.model] = []
            model_stats[call.model].append(call.duration)

        for model, model_durations in model_stats.items():
            model_durations.sort()
            n_model = len(model_durations)
            stats[f"model_{model}"] = {
                "count": n_model,
                "total": sum(model_durations),
                "min": min(model_durations),
                "max": max(model_durations),
                "mean": sum(model_durations) / n_model,
                "p50": model_durations[n_model // 2],
                "p95": (
                    model_durations[int(n_model * 0.95)]
                    if n_model > 1
                    else model_durations[0]
                ),
                "p99": (
                    model_durations[int(n_model * 0.99)]
                    if n_model > 1
                    else model_durations[0]
                ),
            }

        return stats

    def get_summary(self) -> Dict[str, Union[float, int]]:
        """Get a summary of all timing data."""
        summary = {
            "total_experiment_clock_time": self.get_experiment_duration() or 0.0,
            "total_llm_time": self.get_total_llm_time(),
            "llm_call_count": self.get_llm_call_count(),
        }

        # Add individual LLM call times
        for i, call in enumerate(self.llm_calls, 1):
            summary[f"model_provider_call_{i}"] = call.duration

        return summary

    def to_json(self) -> Dict[str, Any]:
        """Export timing data as structured JSON."""
        return asdict(
            ExperimentTiming(
                experiment_id=self._experiment_id or "unknown",
                app_name=self._app_name or "unknown",
                start_time=self.experiment_start_time or 0.0,
                end_time=self.experiment_end_time or 0.0,
                total_duration=self.get_experiment_duration() or 0.0,
                llm_calls=self.llm_calls,
                total_llm_time=self.get_total_llm_time(),
                llm_call_count=self.get_llm_call_count(),
                stats=self._compute_stats(),
            )
        )

    def save_json(self, filepath: Path) -> None:
        """Save timing data to JSON file."""
        with open(filepath, "w") as f:
            json.dump(self.to_json(), f, indent=2)

    def log_summary(self, logger) -> None:
        """Log timing summary to the provided logger."""
        # Timing summary logging temporarily disabled
        pass


# Global time tracker instance
time_tracker = TimeTracker()
