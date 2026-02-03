"""LiteLLM provider for unified model access.

Uses LiteLLM's native Chat Completions interface for simplicity.
Supports OpenAI, Anthropic, Google, and other models through LiteLLM.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import litellm

from utils.logger import agent_logger

from .base import ModelProvider

# Suppress LiteLLM's verbose logging
litellm.suppress_debug_info = True


class LiteLLMProvider(ModelProvider):
    """LiteLLM-based provider using native Chat Completions interface.

    This provider uses LiteLLM's stateless completion API directly.
    The agent is responsible for managing conversation history.
    """

    def __init__(self) -> None:
        self._validated: bool = False

        # Configure LiteLLM settings
        litellm.drop_params = True  # Drop unsupported params instead of erroring
        litellm.set_verbose = False  # Reduce noise in logs

    def _detect_provider_from_model(self, model: str) -> str:
        """Detect the provider from the model name."""
        model_lower = model.lower()

        if any(p in model_lower for p in ["gemini", "gemma", "learnlm", "imagen"]):
            return "gemini"
        if any(p in model_lower for p in ["claude", "anthropic"]):
            return "anthropic"
        if any(
            p in model_lower
            for p in ["gpt", "o1", "o3", "o4", "davinci", "curie", "babbage", "ada"]
        ):
            return "openai"

        # Default to OpenAI
        return "openai"

    def _get_litellm_model_name(self, model: str) -> str:
        """Convert model name to LiteLLM format if needed.

        LiteLLM uses prefixes for non-OpenAI models:
        - gemini/gemini-pro -> Gemini
        - anthropic/claude-3-opus -> Anthropic
        - gpt-4 -> OpenAI (no prefix needed)
        """
        model_lower = model.lower()

        # Gemini models need the gemini/ prefix
        if any(p in model_lower for p in ["gemini", "gemma", "learnlm"]):
            if not model.startswith("gemini/"):
                return f"gemini/{model}"

        # Anthropic models need the anthropic/ prefix
        if "claude" in model_lower:
            if not model.startswith("anthropic/"):
                return f"anthropic/{model}"

        return model

    def _get_required_api_key_env(self, model: str) -> tuple[str, str]:
        """Get the required API key environment variable for a model.

        Returns:
            Tuple of (env_var_name, provider_name)
        """
        provider = self._detect_provider_from_model(model)

        if provider == "gemini":
            return "GEMINI_API_KEY", "Google Gemini"
        if provider == "anthropic":
            return "ANTHROPIC_API_KEY", "Anthropic"
        # Default to OpenAI
        return "OPENAI_API_KEY", "OpenAI"

    def validate(self, model: str = None) -> None:
        """Validate that required API keys are set.

        Args:
            model: Optional model name to validate specific provider.
                   If not provided, validates OpenAI as default.
        """
        if model:
            env_var, provider_name = self._get_required_api_key_env(model)
        else:
            env_var, provider_name = "OPENAI_API_KEY", "OpenAI"

        api_key = os.getenv(env_var)
        if not api_key or not api_key.strip():
            raise ValueError(
                f"{env_var} environment variable is required but not set. "
                f"Please ensure your .env file contains {env_var}=your-actual-key-here "
                "or set the environment variable directly."
            )

        self._validated = True
        agent_logger.info(
            f"{provider_name} API key found for model '{model or 'default'}'"
        )

    def _convert_tools_to_litellm(self, tools: Optional[List]) -> Optional[List]:
        """Convert tool definitions to LiteLLM format.

        LiteLLM uses OpenAI's tool format, so this is mostly passthrough.
        """
        if not tools:
            return None

        litellm_tools = []
        for tool in tools:
            if isinstance(tool, dict):
                if "function" in tool:
                    # Already in OpenAI format
                    litellm_tools.append(tool)
                elif "name" in tool and "parameters" in tool:
                    # Convert to OpenAI format
                    litellm_tools.append(
                        {
                            "type": "function",
                            "function": {
                                "name": tool["name"],
                                "description": tool.get("description", ""),
                                "parameters": tool["parameters"],
                            },
                        }
                    )

        return litellm_tools if litellm_tools else None

    def call(
        self,
        *,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        max_output_tokens: Optional[int] = None,
        timeout_ms: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """Call the model using LiteLLM's completion API.

        Args:
            model: Model identifier (e.g., "gpt-4", "claude-3-opus")
            messages: List of message dicts with role and content
            tools: Optional list of tool definitions
            max_output_tokens: Maximum tokens in response
            timeout_ms: Request timeout in milliseconds
            reasoning_effort: For reasoning models (o1, etc.)
            **kwargs: Additional arguments passed to litellm.completion

        Returns:
            LiteLLM ChatCompletion response object (OpenAI-compatible)
        """
        if not self._validated:
            raise RuntimeError(
                "LiteLLM provider not validated. Call validate() before making API calls."
            )

        litellm_model = self._get_litellm_model_name(model)

        # Build completion kwargs
        completion_kwargs: Dict[str, Any] = {
            "model": litellm_model,
            "messages": messages,
        }

        # Add tools if provided
        litellm_tools = self._convert_tools_to_litellm(tools)
        if litellm_tools:
            completion_kwargs["tools"] = litellm_tools
            completion_kwargs["tool_choice"] = "auto"

        if max_output_tokens:
            completion_kwargs["max_tokens"] = max_output_tokens

        if timeout_ms:
            completion_kwargs["timeout"] = timeout_ms / 1000.0  # Convert to seconds

        # Handle reasoning/thinking for supported models
        # LiteLLM's drop_params=True will ignore unsupported params gracefully
        if reasoning_effort:
            provider = self._detect_provider_from_model(model)

            if provider == "openai":
                # OpenAI reasoning models (o1, o3, o4, gpt-5, future models)
                # Non-reasoning models will ignore this param due to drop_params=True
                completion_kwargs["reasoning_effort"] = reasoning_effort

            elif provider == "gemini":
                # Gemini thinking (2.0+, future versions)
                # Budget range: 1024-24576 tokens
                budget = 8192  # default/medium
                if "low" in reasoning_effort:
                    budget = 2048
                elif "high" in reasoning_effort:
                    budget = 16384
                completion_kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": budget,
                }

            elif provider == "anthropic":
                # Claude extended thinking (3.5+, future versions)
                # Budget range similar to Gemini
                budget = 8192  # default/medium
                if "low" in reasoning_effort:
                    budget = 2048
                elif "high" in reasoning_effort:
                    budget = 16384
                completion_kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": budget,
                }

        # Add any extra kwargs
        completion_kwargs.update(kwargs)

        agent_logger.info(
            f"LiteLLM API request: model={litellm_model}, messages={len(messages)}, "
            f"tools={len(litellm_tools) if litellm_tools else 0}"
        )

        # Make the API call
        response = litellm.completion(**completion_kwargs)

        return response
