from __future__ import annotations

import re

TOKENS_PER_MILLION = 1_000_000.0
COST_PRECISION = 10

PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
SUPPORTED_PROVIDERS = [PROVIDER_OPENAI, PROVIDER_ANTHROPIC]

FIELD_INPUT = "input"
FIELD_OUTPUT = "output"
FIELD_REASONING = "reasoning"

FIELD_CACHE_INPUT = "cache_input"

# Anthropic style cache fields
FIELD_CACHE_HITS_AND_REFRESHES = "cache_hits_and_refreshes"
FIELD_CACHE_WRITE = "cache_write"

OPENAI_DATE_PATTERN = re.compile(r"-\d{4}-\d{2}-\d{2}$")
ANTHROPIC_DATE_PATTERN = re.compile(r"-\d{8}$")

ANTHROPIC_MODEL_MAPPINGS = {
    "claude-opus-4-1-20250805": "claude-opus-4-1",
    "claude-opus-4-0": "claude-opus-4",
    "claude-opus-4-20250514": "claude-opus-4",
    "claude-4-opus-20250514": "claude-opus-4",
    "claude-sonnet-4-0": "claude-sonnet-4",
    "claude-sonnet-4-20250514": "claude-sonnet-4",
    "claude-4-sonnet-20250514": "claude-sonnet-4",
    "claude-3-7-sonnet-latest": "claude-sonnet-3-7",
    "claude-3-7-sonnet-20250219": "claude-sonnet-3-7",
    "claude-3-5-haiku-latest": "claude-haiku-3-5",
    "claude-3-5-haiku-20241022": "claude-haiku-3-5",
}
