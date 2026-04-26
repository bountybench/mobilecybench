# Adding a New Model

The model id you put in `runner_config.json:model` is sent to the underlying
API. There are two integration tiers; pick whichever fits.

## Tier 1 — drop in by name (no code change)

If your model id contains a substring already known to LiteLLM
(`claude`/`anthropic`, `gemini`/`gemma`/`learnlm`/`imagen`, plus anything
added via `register_provider`), put it in your config and set the matching
`*_API_KEY` in `agent/.env`:

```json
{ "model": "claude-new-model", "agent_mode": "custom" }
```

The agent logs a `WARNING` and proceeds. The pipeline does not fail. This
is enough to get a working evaluation loop in front of a model in minutes,
but **token costs are not tracked** until you add an entry to `utils/token_pricing.json`.

## Tier 2 — first-class support (recommended for sustained use)

Tier 1 keeps running, but until you complete two edits you give up:

| Without first-class support | Impact |
|-----------------------------|--------|
| No row in `utils/token_pricing.json` | `run_summary.json:metrics.cost_usd` reports `0.0`. **Aggregated dashboards silently understate spend** — every budget check, cost comparison, or cost/run number is wrong. |
| No entry in `agent/model_providers/factory.py:SupportedModel` | Noisy `WARNING` on every run; model is invisible to anyone listing supported models. |

Both are quick edits and should land in the same change as the model.

A third reason to register — only relevant for OpenAI-Responses-API-shaped
endpoints — is covered in [Path A](#path-a--openai-responses-api). All
other providers (Chat Completions / LiteLLM) get **identical behaviour**
whether the model is registered or not; the entry is purely metadata.

---

## How to register (Tier 2)

### 1. Add to `SupportedModel`

`agent/model_providers/factory.py`:

```python
class SupportedModel(Enum):
    ...
    MY_MODEL = ModelConfig("my-model-id", "litellm")  # or "openai"
```

### 2. Add pricing

`utils/token_pricing.json` (USD per 1M tokens, schema in `utils/token_costs.py`):

```json
"my-model-id": {
  "input": 2.5,
  "output": 15.0,
  "cache_input": 0.25,
  "reasoning": 15.0
}
```

Omit `reasoning` if your model doesn't expose reasoning tokens (falls back
to the output rate). Use the optional `high_context` block for tiered
pricing.

### 3. Add the env var to `agent/.env.example`

So future users know the variable exists.

### 4. Smoke-test

```bash
# Set dry_run: true in runner_config.json
python runner.py conversations
```

Open `logs/latest/conversation.jsonl` and confirm at least one turn has
non-empty `assistant_text` and a tool call.

---

## When you need more than Tier 2

### Path A — OpenAI Responses API

If your endpoint serves `POST /v1/responses` (encrypted reasoning,
server-side state via `previous_response_id`, etc.), register with
`provider="openai"`. Without this, an unknown OpenAI-shaped model falls
through to `LiteLLMProvider`, which uses `/v1/chat/completions` — those
Responses-API features are unavailable.

```python
MY_MODEL = ModelConfig("my-model-id", "openai")
```

Set `OPENAI_API_KEY` (and `OPENAI_BASE_URL` if not `api.openai.com`).

### Path B — LiteLLM with an unrecognized model name

If your model id has no substring in the detection registry (e.g.
`super-1`), the fallback routes to `OPENAI_API_KEY` and `litellm.completion`
won't have a route. Add a detection rule.

Inline (preferred — commit it):

```python
# agent/model_providers/litellm_provider.py
_PROVIDER_REGISTRY: List[ProviderRule] = [
    ProviderRule(("myprovider",), "myprovider", "MYPROVIDER_API_KEY",
                 "MyProvider", litellm_prefix="openai/"),
    # ... built-ins ...
]
```

Or at runtime, before `setup_agent()` runs:

```python
from agent.model_providers.litellm_provider import register_provider
register_provider(("myprovider",), "myprovider", "MYPROVIDER_API_KEY",
                  "MyProvider", litellm_prefix="openai/")
```

Either way, also add the model to `SupportedModel` and pricing to
`token_pricing.json`.

### Path C — Custom provider

If the API is neither Responses-API nor Chat-Completions-shaped, write a
new `ModelProvider` subclass. The contract is in
`agent/model_providers/base.py`; `OpenAIProvider` and `LiteLLMProvider` are
worked references.

```python
# agent/model_providers/myprovider.py
class MyProviderProvider(ModelProvider):
    def __init__(self, model, instructions, tools=None,
                 max_output_tokens=None, timeout_ms=None,
                 reasoning_effort=None):
        super().__init__()
        # validate API key, build client, init conversation state

    def call(self, input):
        # 1. translate `input` into your request shape
        # 2. send the request
        # 3. parse response into ProviderResponse
        #    (assistant_text, reasoning_summary, function_calls)
        # 4. self._record_history(resp); return resp
```

Then route to it from `factory.py:get_model_provider`:

```python
if entry.value.provider == "myprovider":
    from .myprovider import MyProviderProvider
    return MyProviderProvider(**kwargs)
```

Notes:
- `input` follows the OpenAI Responses API shape — string on first turn,
  then a list of `{"type": "message"|"function_call_output", ...}`. See
  `LiteLLMProvider._translate_input_to_messages` for a worked translation
  to Chat Completions.
- `tools` is provider-neutral: `[{"name", "description", "parameters"}]`.
- Conversation state can be server-side (a chain id, like
  `OpenAIProvider._previous_response_id`) or client-side (a messages
  array, like `LiteLLMProvider._messages`).

---

## Common pitfalls

- **Cost reported as `0`.** Missing `token_pricing.json` row.
- **Agent loops with empty responses.** Your provider isn't filling
  `ProviderResponse.assistant_text` or `function_calls`; the agent nudges
  and retries until `max_iterations`.
- **`ValueError: <ENV>_API_KEY environment variable is required`.** Either
  the var isn't set, or your model name's substring matches the wrong
  detection rule.
- **Detection ambiguity.** A name like `claude-router-v1` is routed to
  Anthropic by the `claude` substring. Add a more specific rule before
  the built-ins (new rules go to the front and win).
