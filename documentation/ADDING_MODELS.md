# Adding a New Model

The model id you put in `runner_config.json:model` is sent to the underlying
API. By default the runner only accepts models declared in
`agent/model_providers/factory.py:SupportedModel`; this doc covers how to
add one (the standard path) and how to bypass the registry temporarily for
exploration (only use if you do not care about cost tracking).

## Standard path — register the model

Three short edits plus a smoke-test:

### 1. Add to `SupportedModel`

`agent/model_providers/factory.py`:

```python
class SupportedModel(Enum):
    ...
    MY_MODEL = ModelConfig("my-model-id", "litellm")  # or "openai"
```

Provider tag:
- `"openai"` — routed through `OpenAIProvider` (Responses API; encrypted
  reasoning, server-side state via `previous_response_id`).
- `"litellm"` — routed through `LiteLLMProvider` (Chat Completions). The
  provider's name-substring detection auto-picks the right `*_API_KEY`.
  If LiteLLM doesn't recognise your model's name (e.g. `super-1`), see
  [Custom provider name](#custom-provider-name) below before this step.

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
pricing on long prompts.

### 3. Add the env var to `agent/.env.example`

A placeholder line so future users know the variable exists.

### 4. Smoke-test

`runner.py --config runner_config_dryrun.json` (or `dry_run: true` in the config) launches an interactive Kali shell instead of the agent — useful for verifying the runtime environment, but it never invokes the provider, so it can't validate a model integration. Use the dedicated provider smoke-test:

```bash
python scripts/smoke_test_model.py
```

By default it picks up `model` from `runner_config.json` and sends a trivial single-token prompt. Pass `--model my-model-id` to override. Exit codes:

- `0` — provider returned a non-empty response (model integration is wired up).
- `1` — configuration or API-key error (provider couldn't be constructed).
- `2` — provider raised at call time (network / 4xx / 5xx).

Sample success output for `gpt-5.5`:

```
smoke-test: model='gpt-5.5' allow_unregistered=False
smoke-test: provider=OpenAIProvider
smoke-test: prompt='Reply with the single word "OK". No tools, no JSON, just OK.'

OK in 2.10s
  response_id     = 'resp_…'
  assistant_text  = 'OK'
```

Once the smoke-test passes, do a one-iteration real run to exercise the agent loop:

```bash
# Set max_iterations: 1 in runner_config.json (keep dry_run: false), then:
python runner.py conversations
```

Open `logs/latest/conversation.jsonl` and confirm the single turn has non-empty `assistant_text` (or `reasoning_summary`) and at least one tool call.

---

## Quick alternative — `allow_unregistered_models`

Set this in `runner_config.json` to skip the registry check:

```json
{ "model": "claude-some-variant", "allow_unregistered_models": true }
```

The agent logs a `WARNING` and proceeds. The model still has to route
through LiteLLM, so its name needs a substring the detection registry
recognises (or a runtime rule via `register_provider`); see
[Custom provider name](#custom-provider-name) below.

`cost_usd` will report `$0` for any model not in
`utils/token_pricing.json`, so any cost-aware downstream consumer
(dashboards, budget checks, cost-per-task aggregation) will be wrong.

When to use it:
- Comparing 5-10 model variants in a one-off shootout you'll throw away.
- Trying a preview model whose pricing isn't public yet.
- Smoke-testing an unfamiliar model id before committing to register it.

When **not** to use it:
- Sustained eval runs whose results feed reports or comparisons.
- Anything where someone might later read `cost_usd` from the run summary.

For one-off use, register the winner permanently after the sweep so future
runs land on the standard path.

---

## Custom provider name

The LiteLLM provider picks the right API key by matching substrings in
the model id. The built-in rules cover `claude`/`anthropic`,
`gemini`/`gemma`/`learnlm`/`imagen`. Anything else falls through to
`OPENAI_API_KEY` — and `litellm.completion` will then fail because it
has no route for the model.

If your model name doesn't match a built-in substring, add a rule first.

Inline (preferred — commit it alongside the model entry):

```python
# agent/model_providers/litellm_provider.py
_PROVIDER_REGISTRY: List[ProviderRule] = [
    ProviderRule(("myprovider",), "myprovider", "MYPROVIDER_API_KEY",
                 "MyProvider", litellm_prefix="openai/"),
    # ... built-ins ...
]
```

Or at runtime, from a bootstrap import before `setup_agent()` runs:

```python
from agent.model_providers.litellm_provider import register_provider
register_provider(("myprovider",), "myprovider", "MYPROVIDER_API_KEY",
                  "MyProvider", litellm_prefix="openai/")
```

`register_provider` inserts the rule at the front of the registry, so it
always takes precedence over the built-in defaults.

---

## Fully custom provider

If the API is neither Responses-API nor Chat-Completions-shaped, write a
new `ModelProvider` subclass. The contract is in
`agent/model_providers/base.py`; `OpenAIProvider` and `LiteLLMProvider`
are worked references.

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

Route to it from `factory.py:get_model_provider`:

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

- **`ValueError: Unsupported model`.** Default deny. Register the model
  per the standard path, or set `allow_unregistered_models: true` for
  exploration only.
- **Cost reported as `0`.** Missing `token_pricing.json` row. The
  `allow_unregistered_models` flag does not fix this; pricing is a
  separate edit.
- **Agent loops with empty responses.** Your provider isn't filling
  `ProviderResponse.assistant_text` or `function_calls`; the agent
  nudges and retries until `max_iterations`.
- **`ValueError: <ENV>_API_KEY environment variable is required`.**
  Either the var isn't set, or your model name's substring matches the
  wrong detection rule.
- **Detection ambiguity.** A name like `claude-router-v1` is routed to
  Anthropic by the `claude` substring. Add a more specific rule before
  the built-ins (new rules go to the front and win).
