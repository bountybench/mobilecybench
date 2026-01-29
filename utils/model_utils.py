"""
Utilities for LLM/model interactions.

Includes shared logic for format reinforcement messages to prevent model drift.

TODO: gpt-5.1-2025-11-13 still returns empty API responses (0 chars) even with
format reinforcement on every turn. gemini-3-pro-preview does not have this issue.

TODO: Gemini provider needs SDK migration from google.generativeai to google.genai.Client.
See: https://github.com/google-gemini/deprecated-generative-ai-python
End-of-Life Date: All support for this repository ended permanently on November 30, 2025.
Include reasoning_summary support during the migration.
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
