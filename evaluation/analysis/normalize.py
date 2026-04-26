"""Shared accessors for `run_summary.json`.

Pure helpers that any analyzer can use to extract canonical fields from a
parsed run summary. Per-agent token-shape differences are normalized here
so analyzers don't have to know which agent backend produced a run.

Mapping table is documented in `documentation/LOG_POSTPROCESSING_PLAN.md` (§4a).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CANONICAL_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "cost_usd",
    "calls",
)


def load_run_summary(exp_dir: Path) -> tuple[dict | None, str | None]:
    """Load `<exp_dir>/run_summary.json`.

    Returns `(summary, None)` on success, `(None, reason)` if missing or
    unparseable. Callers should check `reason` to distinguish missing-file
    from corrupt-file cases.
    """
    p = exp_dir / "run_summary.json"
    if not p.exists():
        return None, "missing"
    try:
        return json.loads(p.read_text()), None
    except json.JSONDecodeError as e:
        return None, f"json_decode: {e}"


def normalize_token_totals(summary: dict) -> dict[str, Any]:
    """Map per-agent `metrics.token_totals` shapes to canonical keys.

    Missing fields are `None` (never `0`) so analyzers can distinguish
    "not reported" from "reported as zero".
    """
    metrics = summary.get("metrics") or {}
    totals = metrics.get("token_totals") or {}
    agent_type = (summary.get("context") or {}).get("agent_type")

    def g(*keys: str) -> Any:
        for k in keys:
            v = totals.get(k)
            if v is not None:
                return v
        return None

    if agent_type == "claude-code":
        return {
            "input_tokens": g("input_tokens"),
            "output_tokens": g("output_tokens"),
            "reasoning_tokens": None,
            "cache_read_tokens": g("cache_read_input_tokens"),
            "cache_creation_tokens": g("cache_creation_input_tokens"),
            "cost_usd": g("cost_usd"),
            "calls": _claude_code_calls(totals),
        }
    if agent_type == "codex":
        return {
            "input_tokens": g("input_tokens"),
            "output_tokens": g("output_tokens"),
            "reasoning_tokens": g("reasoning_output_tokens"),
            "cache_read_tokens": g("cached_input_tokens"),
            "cache_creation_tokens": None,
            "cost_usd": None,
            "calls": g("calls"),
        }
    # custom or unknown — same shape as utils/token_tracker.py:303
    return {
        "input_tokens": g("input_tokens"),
        "output_tokens": g("output_tokens"),
        "reasoning_tokens": g("reasoning_tokens"),
        "cache_read_tokens": g("cache_input_tokens"),
        "cache_creation_tokens": None,
        "cost_usd": g("cost_usd"),
        "calls": g("calls"),
    }


def _claude_code_calls(totals: dict) -> int | None:
    """Claude-code emits no top-level `calls`; estimate from `per_model`."""
    per_model = totals.get("per_model")
    if isinstance(per_model, dict) and per_model:
        return len(per_model)
    return None


def get_cost_usd(summary: dict) -> float | None:
    """Prefer `metrics.cost_usd`; fall back to `metrics.token_totals.cost_usd`."""
    metrics = summary.get("metrics") or {}
    if metrics.get("cost_usd") is not None:
        return metrics["cost_usd"]
    totals = metrics.get("token_totals") or {}
    return totals.get("cost_usd")


def get_timing(summary: dict) -> dict[str, Any]:
    """Pull `metrics.timing` with `_llm_s`-suffixed keys."""
    timing = (summary.get("metrics") or {}).get("timing") or {}
    return {
        "total_llm_time_s": timing.get("total_llm_time"),
        "llm_call_count": timing.get("llm_call_count"),
        "p50_llm_s": timing.get("p50"),
        "p95_llm_s": timing.get("p95"),
        "max_llm_s": timing.get("max"),
    }


def get_context(summary: dict) -> dict[str, Any]:
    ctx = summary.get("context") or {}
    return {
        "app": ctx.get("app_name"),
        "vuln_id": ctx.get("vuln_id"),
        "workflow": ctx.get("workflow"),
        "model": ctx.get("model"),
        "agent_type": ctx.get("agent_type"),
    }


def get_results(summary: dict) -> dict[str, Any]:
    """Surface score, status, and agent_status — they encode different things."""
    r = summary.get("results") or {}
    return {
        "score": r.get("score"),
        "status": r.get("status"),
        "agent_status": r.get("agent_status"),
        "inconsistencies": r.get("inconsistencies") or [],
    }


def is_pass(summary: dict) -> bool:
    """Headline pass criterion: `results.score == 1`.

    Outcome=success with score!=1 (e.g. dry-run/gold completion) is not a pass.
    """
    score = (summary.get("results") or {}).get("score")
    return score == 1 or score == 1.0


def csv_encode(value: Any) -> str:
    """Encode a value for CSV cells.

    Lists/dicts → `json.dumps(..., sort_keys=True)` (round-trippable);
    `None` → empty string; bools → `true`/`false`; everything else → `str()`.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True)
    return str(value)
