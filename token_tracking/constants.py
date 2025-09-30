import re

TOKENS_PER_MILLION = 1_000_000.0
COST_PRECISION = 10

PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
SUPPORTED_PROVIDERS = [PROVIDER_OPENAI, PROVIDER_ANTHROPIC]

# field names for pricing components
INPUT_PRICE_FIELD = "input"
OUTPUT_PRICE_FIELD = "output"
REASONING_PRICE_FIELD = "reasoning"

CACHE_INPUT_PRICE_FIELD = "cache_input"

# Anthropic style cache fields
CACHE_HITS_AND_REFREeSHES_PRICE_FIELD = "cache_hits_and_refreshes"
CACHE_WRITE_PRICE_FIELD = "cache_write"

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
