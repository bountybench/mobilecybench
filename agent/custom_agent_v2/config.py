"""
Configuration for custom_agent_v2 including LangSmith integration and model settings.

This module provides:
1. LangSmith tracing setup for debugging
2. GPT-5.2 model configuration with reasoning mode
3. Agent default settings
4. Memory/checkpointing configuration
"""

import os
from typing import Optional

from dotenv import load_dotenv

from utils.logger import agent_logger

# Load environment variables
load_dotenv()


class AgentConfig:
    """Configuration constants for the agent system."""

    # Model Configuration
    MODEL_DEFAULT = "gpt-5.2"  # GPT-5.2 Thinking model
    MODEL_INSTANT = "gpt-5.2-chat-latest"  # GPT-5.2 Instant (faster, no reasoning)
    MODEL_PRO = "gpt-5.2-pro"  # GPT-5.2 Pro (most accurate)

    # Reasoning Configuration
    REASONING_EFFORT_DEFAULT = "medium"
    REASONING_ENABLED_DEFAULT = True

    # Valid reasoning effort levels
    REASONING_EFFORTS = ["low", "medium", "high", "very_high", "xhigh"]

    # Temperature
    TEMPERATURE_DEFAULT = 0

    # LangSmith
    LANGSMITH_PROJECT_DEFAULT = "mobile-cyber-agent"


def setup_langsmith(
    project_name: Optional[str] = None, enabled: bool = True
) -> None:
    """
    Configure LangSmith tracing for debugging and monitoring.

    LangSmith provides:
    - Trace visualization of agent execution
    - Tool call logging
    - Reasoning step inspection
    - Performance monitoring
    - Error debugging

    Args:
        project_name: LangSmith project name (default: "mobile-cyber-agent")
        enabled: Whether to enable LangSmith tracing (default: True)

    Environment Variables Required:
        LANGCHAIN_API_KEY: Your LangSmith API key (from https://smith.langchain.com)

    Example:
        >>> setup_langsmith()  # Uses default project name
        >>> setup_langsmith(project_name="my-custom-project")
        >>> setup_langsmith(enabled=False)  # Disable tracing
    """
    if not enabled:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        agent_logger.info("LangSmith tracing disabled")
        return

    # Check if API key is set
    api_key = os.getenv("LANGCHAIN_API_KEY")
    if not api_key:
        agent_logger.warning(
            "LANGCHAIN_API_KEY not found in environment. LangSmith tracing will be disabled."
        )
        agent_logger.warning(
            "To enable LangSmith tracing, add LANGCHAIN_API_KEY=lsv2_pt_... to your .env file"
        )
        agent_logger.warning("Get your API key from: https://smith.langchain.com")
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return

    # Enable tracing
    os.environ["LANGCHAIN_TRACING_V2"] = "true"

    # Set project name
    project = project_name or AgentConfig.LANGSMITH_PROJECT_DEFAULT
    os.environ["LANGCHAIN_PROJECT"] = project

    agent_logger.info(f"LangSmith tracing enabled for project: {project}")
    agent_logger.info(
        "View traces at: https://smith.langchain.com/projects/{}".format(
            project.replace(" ", "%20")
        )
    )


def get_model_config(
    model: str = AgentConfig.MODEL_DEFAULT,
    reasoning_effort: str = AgentConfig.REASONING_EFFORT_DEFAULT,
    enable_reasoning: bool = AgentConfig.REASONING_ENABLED_DEFAULT,
    temperature: float = AgentConfig.TEMPERATURE_DEFAULT,
) -> dict:
    """
    Get model configuration for ChatOpenAI.

    Args:
        model: OpenAI model to use (default: gpt-5.2)
        reasoning_effort: Reasoning effort level for GPT-5.2 (default: medium)
                          Options: low, medium, high, very_high, xhigh
        enable_reasoning: Whether to enable reasoning mode (default: True)
        temperature: Model temperature (default: 0 for deterministic)

    Returns:
        Dictionary with model kwargs for ChatOpenAI initialization

    Example:
        >>> config = get_model_config()
        >>> config = get_model_config(reasoning_effort="high")
        >>> config = get_model_config(enable_reasoning=False)
    """
    # Validate reasoning effort
    if reasoning_effort not in AgentConfig.REASONING_EFFORTS:
        agent_logger.warning(
            f"Invalid reasoning_effort '{reasoning_effort}'. "
            f"Valid options: {AgentConfig.REASONING_EFFORTS}. "
            f"Using default: {AgentConfig.REASONING_EFFORT_DEFAULT}"
        )
        reasoning_effort = AgentConfig.REASONING_EFFORT_DEFAULT

    # Build model kwargs
    model_kwargs = {}

    # Add reasoning parameters if enabled
    if enable_reasoning and model in [
        AgentConfig.MODEL_DEFAULT,
        AgentConfig.MODEL_PRO,
    ]:
        model_kwargs["reasoning_effort"] = reasoning_effort
        agent_logger.info(
            f"Reasoning mode enabled with effort level: {reasoning_effort}"
        )
    elif enable_reasoning:
        agent_logger.warning(
            f"Reasoning mode requested but model '{model}' does not support it. "
            f"Use 'gpt-5.2' or 'gpt-5.2-pro' for reasoning."
        )

    config = {
        "model": model,
        "temperature": temperature,
        "model_kwargs": model_kwargs if model_kwargs else {},
    }

    agent_logger.info(
        f"Model configuration: {model}, temperature={temperature}, "
        f"reasoning={'enabled' if (enable_reasoning and model_kwargs) else 'disabled'}"
    )

    return config


def validate_environment() -> bool:
    """
    Validate that required environment variables and dependencies are set.

    Checks:
    - OpenAI API key
    - Docker connection (Kali container)
    - LangSmith (optional, warning if not set)

    Returns:
        True if environment is valid, False otherwise
    """
    issues = []

    # Check OpenAI API key
    if not os.getenv("OPENAI_API_KEY"):
        issues.append("OPENAI_API_KEY not found in environment")

    # Check LangSmith (optional, just warn)
    if not os.getenv("LANGCHAIN_API_KEY"):
        agent_logger.warning(
            "LANGCHAIN_API_KEY not found. LangSmith tracing will be disabled."
        )

    # Check Docker connection
    try:
        from agent.mcp.docker_setup import get_kali

        container = get_kali()
        agent_logger.info(f"Docker connection verified: {container.name}")
    except Exception as e:
        issues.append(f"Docker/Kali container not accessible: {str(e)}")

    # Report issues
    if issues:
        agent_logger.error("Environment validation failed:")
        for issue in issues:
            agent_logger.error(f"  - {issue}")
        return False

    agent_logger.info("Environment validation passed")
    return True


# Initialize LangSmith on module import (can be disabled with env var)
if os.getenv("LANGSMITH_ENABLED", "true").lower() != "false":
    setup_langsmith()
