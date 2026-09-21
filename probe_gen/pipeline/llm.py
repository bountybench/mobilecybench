"""Stateless LLM client for probe-gen pipeline calls.

Wraps :mod:`litellm` (which the repo already depends on) so that every
probe-gen module gets a uniform, one-shot interface across Anthropic,
OpenAI, and Google. Designed for *single-turn* generation calls — the
existing ``agent.model_providers`` infrastructure is for multi-turn
agent loops with tool use, which is heavier than what the pipeline
needs.

Public surface:
  - :func:`complete` — one-shot text generation, returns a string.
  - :func:`complete_json` — same, but parses the model's response as
    JSON (with common-mistake recovery: ```json fences, prose preamble).
  - :class:`LLMResponse` — typed return value with usage + cost.
  - :func:`load_env` — explicit load of ``agent/.env``; usually called
    automatically on first call.

Default routing across families (override per call):
  - Claude Opus 4.7 (``claude-opus-4-7``) — invariant derivation,
    threat-model reasoning. Anthropic's longest-context model.
  - GPT-5.5 (``gpt-5.5``) — patch synthesis, diff manipulation.
  - Gemini 3.1 Pro — adversarial decoy generation (cross-family
    mitigation: a Gemini decoy probing a Claude-generated probe is the
    decoy-gate's load-bearing diversification).

Cost is tracked per call and surfaced via :class:`LLMResponse.cost_usd`.
The pipeline's run summary aggregates cost.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


# Three default models, one per family. Centralized so callers can
# refer to them by role rather than hard-coding strings everywhere.
class DefaultModels:
    INVARIANT_DERIVATION = "claude-opus-4-7"
    PATCH_SYNTHESIS = "gpt-5.5"
    ADVERSARIAL_DECOY = "gemini-3.1-pro"
    THREAT_MODEL_BOOTSTRAP = "claude-opus-4-7"
    PROBE_BODY = "claude-sonnet-4-6"


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    raw: Any = None


_ENV_LOADED = False


def load_env(env_path: Optional[Path] = None, *, override: bool = False) -> Path:
    """Load API-key env vars from ``agent/.env`` (or ``env_path`` if given).

    Idempotent: subsequent calls are no-ops unless ``override=True``.
    Returns the path that was loaded, raises ``FileNotFoundError`` if
    no .env is present.
    """
    global _ENV_LOADED
    if _ENV_LOADED and not override:
        return env_path or _default_env_path()

    path = env_path or _default_env_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"agent/.env not found at {path}. Place API keys there or pass "
            "env_path explicitly to load_env(...)."
        )
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and (override or not os.environ.get(key)):
            os.environ[key] = val
    _ENV_LOADED = True
    return path


def _default_env_path() -> Path:
    """Locate ``agent/.env``.

    Search order:
      1. ``$MOBILECYBENCH_ENV_PATH`` if set.
      2. ``<repo_root>/agent/.env`` (relative to this file).
      3. If the repo root is inside a Claude worktree
         (``.claude/worktrees/<id>/...``), the user's primary repo at
         ``../../../agent/.env``. Worktrees do not share ignored files,
         so the .env lives in the parent checkout.

    The first existing path wins. If none exist, returns option 2 (so
    the resulting ``FileNotFoundError`` points to the natural location).
    """
    explicit = os.environ.get("MOBILECYBENCH_ENV_PATH")
    if explicit:
        return Path(explicit)

    here = Path(__file__).resolve()
    repo_root = here.parents[2]
    primary = repo_root / "agent" / ".env"
    if primary.is_file():
        return primary

    # Worktree fallback: ``<top>/.claude/worktrees/<id>/probe_gen/...``
    parts = repo_root.parts
    if len(parts) >= 3 and parts[-3:-1] == (".claude", "worktrees"):
        outer_root = Path(*parts[:-3])
        outer = outer_root / "agent" / ".env"
        if outer.is_file():
            return outer

    return primary


def _ensure_env() -> None:
    """Load .env if it hasn't been loaded yet. Soft-failing."""
    if _ENV_LOADED:
        return
    try:
        load_env()
    except FileNotFoundError:
        # OK to skip — caller may have already exported API keys.
        pass


# ---------------------------------------------------------------------------
# Core completion calls
# ---------------------------------------------------------------------------


def _supports_temperature_override(model: str) -> bool:
    """OpenAI's GPT-5.x reasoning models reject ``temperature`` overrides.

    LiteLLM forwards the parameter as-is, so the API rejects ``0`` with
    "Only the default (1) value is supported." Skip the parameter for
    these models.
    """
    lower = model.lower()
    if lower.startswith("gpt-5") or lower.startswith("openai/gpt-5"):
        return False
    if "o1" in lower or "o3" in lower or lower.endswith("-reasoning"):
        return False
    return True


def complete(
    prompt: str,
    *,
    model: str = DefaultModels.INVARIANT_DERIVATION,
    system: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
    timeout: int = 120,
) -> LLMResponse:
    """One-shot completion. Returns :class:`LLMResponse`.

    Uses LiteLLM's unified Chat Completions API across providers. For
    LiteLLM-style model names with provider prefix (``gemini/...``,
    ``anthropic/...``), pass through unchanged; for bare model names
    LiteLLM auto-detects the provider.
    """
    _ensure_env()
    import litellm  # type: ignore[import-not-found]

    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "timeout": timeout,
    }
    if _supports_temperature_override(model):
        kwargs["temperature"] = temperature

    response = litellm.completion(**kwargs)

    text = ""
    try:
        text = response["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        text = str(response)

    usage = response.get("usage") or {}
    input_tokens = int(usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or 0)

    cost = 0.0
    try:
        # LiteLLM provides cost calculation utilities
        cost = float(litellm.completion_cost(completion_response=response) or 0.0)
    except Exception:
        cost = 0.0

    return LLMResponse(
        text=text,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(cost, 6),
        raw=response,
    )


# ---------------------------------------------------------------------------
# JSON output extraction
# ---------------------------------------------------------------------------


_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of a text response.

    Handles common LLM output mistakes:
      - Wrapped in ```json ... ``` fence
      - Wrapped in ``` ... ``` fence
      - Leading/trailing prose (extracts first {...} or [...] balanced span)
      - Plain JSON

    Raises :class:`ValueError` if no parseable JSON is found.
    """
    text = text.strip()
    # 1) Try the whole thing
    candidates: list[str] = [text]

    # 2) Strip fences
    fence = _FENCE_RE.search(text)
    if fence:
        candidates.insert(0, fence.group(1).strip())

    # 3) Find the first balanced {...} or [...]
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_str = False
        esc = False
        for i, ch in enumerate(text[start:], start=start):
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : i + 1])
                    break

    last_err: Optional[Exception] = None
    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError as exc:
            last_err = exc
            continue
    raise ValueError(f"no parseable JSON in model output: {last_err}")


def complete_json(
    prompt: str,
    *,
    model: str = DefaultModels.INVARIANT_DERIVATION,
    system: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.0,
    timeout: int = 120,
) -> tuple[Any, LLMResponse]:
    """Like :func:`complete` but parses the response as JSON.

    Returns ``(parsed_json, full_response)`` so callers can also access
    cost / token counts. Raises :class:`ValueError` on parse failure
    after extraction recovery is exhausted.
    """
    json_system = (
        "You output exactly one JSON document and nothing else. "
        "No prose, no markdown fences, no explanation. "
        "If asked to return an array, return an array; if asked to return "
        "an object, return an object."
    )
    full_system = json_system if system is None else f"{json_system}\n\n{system}"
    response = complete(
        prompt,
        model=model,
        system=full_system,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
    )
    parsed = extract_json(response.text)
    return parsed, response


# ---------------------------------------------------------------------------
# Cross-family helpers
# ---------------------------------------------------------------------------


_MODEL_FAMILY = {
    "claude": ("claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"),
    "openai": ("gpt-5.5", "gpt-5.4", "gpt-5.2"),
    "gemini": ("gemini-3.1-pro", "gemini-3-pro-preview"),
}


def family_of(model: str) -> str:
    """Return the family of a model name: ``claude`` / ``openai`` / ``gemini``."""
    lower = model.lower()
    if lower.startswith("claude") or "anthropic" in lower:
        return "claude"
    if lower.startswith("gpt") or "openai" in lower:
        return "openai"
    if lower.startswith("gemini") or "google" in lower:
        return "gemini"
    return "unknown"


def cross_family_pick(exclude: str, *, role: str = "decoy") -> str:
    """Pick a default model from a different family than ``exclude``.

    Used to enforce cross-family adversarial decoy generation: if the
    probe was synthesized with Claude, the decoy attempt should run via
    GPT or Gemini to avoid same-model blindspots.
    """
    excluded_family = family_of(exclude)
    for family, models in _MODEL_FAMILY.items():
        if family != excluded_family and models:
            return models[0]
    # Fallback: any model that isn't the excluded one
    for family, models in _MODEL_FAMILY.items():
        for m in models:
            if m != exclude:
                return m
    return exclude


__all__ = [
    "DefaultModels",
    "LLMResponse",
    "complete",
    "complete_json",
    "cross_family_pick",
    "extract_json",
    "family_of",
    "load_env",
]
