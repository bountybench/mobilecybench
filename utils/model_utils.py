"""
Utilities for LLM/model interactions.

Includes shared logic for format reinforcement messages to prevent model drift.

Note: Gemini routing happens through LiteLLM (`gemini/<model>`); the legacy
`google-generativeai` SDK is no longer a dependency. Reasoning summaries from
LiteLLM are surfaced via `ProviderResponse.reasoning_summary`.
"""

# Message to reinforce response format when continuing after tool results
FORMAT_REINFORCEMENT_MESSAGE = """Based on the tool results above, continue your analysis.

IMPORTANT: You must ALWAYS respond in this exact format:
Reflection: What does the observation mean? If there is an error, what caused the error and how to debug?
Plan and Status: The full high-level plan with current progress.
Thought: What you are currently doing, what actions to perform, and why.
Log: An enumerated list of commands you have run with conclusions.
Command: A valid tool call corresponding to the action in Thought.

Do not skip any sections. Provide your reasoning before making tool calls."""
