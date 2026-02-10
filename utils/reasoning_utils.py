from agent.model_providers.factory import _MODEL_REGISTRY


def is_reasoning_supported_model(model: str) -> bool:
    """Return True if the model supports reasoning/thinking parameters.

    All models in the SupportedModel registry support reasoning.
    """
    return model in _MODEL_REGISTRY
