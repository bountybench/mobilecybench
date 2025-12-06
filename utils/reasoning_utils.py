def is_reasoning_supported_model(model: str) -> bool:
    """
    Return True if the model supports the reasoning.effort parameter.
    Updated as of December 2025 based on OpenAI and Azure-OpenAI docs.
    """
    model_lower = model.lower()

    # Exclude o1-mini explicitly (does NOT support reasoning.effort)
    if "o1-mini" in model_lower:
        return False

    # Supported GPT-5 models and variants
    gpt5_variants = [
        "gpt-5", "gpt-5.1", "gpt-5-mini", "gpt-5-nano",
        "gpt-5-codex", "gpt-5.1-codex", "gpt-5.1-codex-mini"
    ]
    if any(variant in model_lower for variant in gpt5_variants):
        return True

    # Supported o-series reasoning models (legacy)
    o_series_supported = [
        "o1", "o3-mini", "o3", "o4-mini", "o4", "o5", "o2", "o3-nano"
    ]
    
    # Accept any model starting with o and not o1-mini
    if model_lower.startswith("o") and not model_lower.startswith("o1-mini"):
        return True
    if any(o in model_lower for o in o_series_supported):
        return True

    return False
