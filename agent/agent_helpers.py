"""
Shared helper functions for agent implementations.

This module contains utility functions that are used across different agent types
(CustomAgent, CodexAgent, etc.) to avoid code duplication.
"""

from agent.backend.docker_ops import execute_command_internal
from utils.logger import agent_logger


def get_directory_tree() -> str:
    """
    Fetch the directory tree structure (depth 2) from the codebase.
    Returns empty string if tree cannot be retrieved.
    """
    try:
        agent_logger.info("Fetching directory tree structure for initial context...")

        tree_cmd = "tree -L 2 2>/dev/null || (ls -la . && echo '---' && find . -maxdepth 2 -type d | head -50)"

        # execute_command_internal returns the formatted string directly
        tree_output = execute_command_internal(tree_cmd)

        if tree_output:
            lines = tree_output.split("\n")
            output_lines = []
            in_output_section = False

            for line in lines:
                if line.strip().startswith("Output:"):
                    in_output_section = True
                    continue
                if in_output_section:
                    output_lines.append(line)

            # If we found output section, use it; otherwise use the whole thing (might be just output)
            if output_lines:
                cleaned_output = "\n".join(output_lines).strip()
            else:
                # Maybe the output doesn't have headers, use as-is
                cleaned_output = tree_output.strip()

            # Limit output size to avoid token limits (2000 chars should be enough for depth 2)
            if len(cleaned_output) > 2000:
                cleaned_output = cleaned_output[:2000] + "\n... (truncated)"

            if cleaned_output:
                agent_logger.info("[OK] Directory tree retrieved successfully")
                return cleaned_output
            else:
                agent_logger.warning("Directory tree output is empty after cleaning")
                return ""
        else:
            agent_logger.warning("Failed to get directory tree: empty output")
            return ""

    except Exception as e:
        # Don't fail the agent run if tree command fails
        agent_logger.warning(f"Failed to get directory tree: {e}")
        return ""
