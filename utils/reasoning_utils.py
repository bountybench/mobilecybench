def is_reasoning_supported_model(model: str) -> bool:
    """
    Return True if the model supports the reasoning.effort parameter.
    """
    model_lower = model.lower()

    # Exclude o1-mini explicitly (does NOT support reasoning.effort)
    if "o1-mini" in model_lower:
        return False

    # Supported GPT-5 models and variants
    gpt5_variants = [
        "gpt-5",
        "gpt-5.1",
        "gpt-5-mini",
        "gpt-5-nano",
        "gpt-5-codex",
        "gpt-5.1-codex",
        "gpt-5.1-codex-mini",
    ]
    if any(variant in model_lower for variant in gpt5_variants):
        return True

    # Supported o-series reasoning models (legacy)
    o_series_supported = ["o1", "o3-mini", "o3", "o4-mini", "o4", "o5", "o2", "o3-nano"]
    if model_lower.startswith("o") and not model_lower.startswith("o1-mini"):
        return True
    if any(o in model_lower for o in o_series_supported):
        return True

    # Supported Gemini models for reasoning effort
    # Gemini 3 Pro: supports thinkingLevel
    # Gemini 2.5 Pro, 2.5 Flash, 2.5 Flash Preview, Robotics-ER 1.5 Preview: support thinkingBudget
    # Gemini 2.5 Flash-Lite and Flash-Lite Preview: do NOT support thinking
    gemini_supported = [
        "gemini-3-pro",
        "gemini-3-pro-preview",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-preview",
        "robotics-er-1.5-preview",
        "gemini-2.5-flash-live-native-audio-preview",
    ]
    gemini_unsupported = [
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash-lite-preview",
    ]
    # Exclude unsupported Gemini models
    if any(u in model_lower for u in gemini_unsupported):
        return False
    if any(s in model_lower for s in gemini_supported):
        return True

    # Accept any Gemini 3 or Gemini 2.5 model except explicitly unsupported ones
    if ("gemini-3" in model_lower or "gemini-2.5" in model_lower) and not any(
        u in model_lower for u in gemini_unsupported
    ):
        return True

    # Supported Anthropic models (adaptive thinking)
    if "claude-opus-4-6" in model_lower:
        return True

    return False
