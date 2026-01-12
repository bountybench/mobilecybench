"""
DiscEx Agent Tools - LangChain-compatible tools for Discovery and Exploit phases.

Discovery Phase Tools: RAG-based code analysis
Exploit Phase Tools: ADB-based dynamic testing

IMPORTANT: All tools execute inside the kali-container for security isolation.
"""

import json
from typing import Optional

from langchain_core.tools import tool

from agent.backend.docker_ops import execute_command_internal, get_ui_state
from agent.preprocessing.vector_store import get_vector_store

# Container paths
CONTAINER_CODEBASE_PATH = "/app/codebase"
CONTAINER_EXPLOIT_PATH = "/app/exploit_files/exploit.sh"


# =============================================================================
# DISCOVERY PHASE TOOLS (RAG-based)
# =============================================================================


@tool
def search_code_pattern(query: str, file_pattern: Optional[str] = None) -> str:
    """
    Fast keyword/regex search using ripgrep in the codebase.

    Args:
        query: Search pattern (supports regex)
        file_pattern: Optional file glob filter (e.g., '*.java')

    Returns:
        JSON array of matches with file, line, and text
    """
    # Build ripgrep command to run in container
    # Escape single quotes in query
    query_escaped = query.replace("'", "'\\''")
    cmd = f"rg --json '{query_escaped}' {CONTAINER_CODEBASE_PATH}"

    if file_pattern:
        pattern_escaped = file_pattern.replace("'", "'\\''")
        cmd += f" --glob '{pattern_escaped}'"

    try:
        # Execute command inside container
        output = execute_command_internal(cmd)

        #Parse output to extract ripgrep JSON results
        matches = []
        for line in output.split("\n"):
            if not line.strip() or line.startswith("Command:") or line.startswith("Output:"):
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    matches.append(
                        {
                            "file": data["data"]["path"]["text"],
                            "line": data["data"]["line_number"],
                            "text": data["data"]["lines"]["text"].strip(),
                        }
                    )
            except json.JSONDecodeError:
                continue

        return json.dumps(matches[:20], indent=2)  # Limit to 20 results
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def semantic_search(query: str, top_k: int = 5) -> str:
    """
    Semantic search using vector embeddings to find code similar to the query.

    Args:
        query: Natural language query describing the code you're looking for
        top_k: Number of results to return (default: 5)

    Returns:
        JSON array of matching code chunks with file, text, and similarity score
    """
    vector_store = get_vector_store()

    try:
        results = vector_store.search(query, limit=top_k)

        formatted = [
            {
                "file": r.get("file_path", "unknown"),
                "text": r.get("text", "")[:300],  # Truncate for readability
                "score": round(r.get("_distance", 0.0), 3),
                "line": r.get("start_line", 0),
            }
            for r in results
        ]

        return json.dumps(formatted, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def read_source_file(file_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
    """
    Read source code file (or specific line range).

    Args:
        file_path: Relative path from codebase root (e.g., 'src/MainActivity.java')
        start_line: Optional starting line number (1-indexed)
        end_line: Optional ending line number (1-indexed)

    Returns:
        File contents (or specified line range)
    """
    # Execute command inside container
    full_path = f"{CONTAINER_CODEBASE_PATH}/{file_path}"

    try:
        if start_line is not None and end_line is not None:
            # Use sed to extract specific line range
            cmd = f"sed -n '{start_line},{end_line}p' {full_path}"
        else:
            # Read entire file with head to limit size
            cmd = f"head -c 10000 {full_path}"

        output = execute_command_internal(cmd)

        # Remove command echo from output
        if "Command:" in output and "Output:" in output:
            output = output.split("Output:", 1)[1].strip()

        return output if output else f"Error: Could not read file: {file_path}"

    except Exception as e:
        return f"Error reading file: {str(e)}"


# =============================================================================
# EXPLOIT PHASE TOOLS (ADB-based)
# =============================================================================


@tool
def execute_adb_command(command: str) -> str:
    """
    Execute ADB shell command or other system commands for dynamic testing.

    Args:
        command: Shell command to execute

    Returns:
        Command output or error message
    """
    try:
        return execute_command_internal(command)
    except Exception as e:
        return f"Error executing command: {str(e)}"


@tool
def get_ui_state_tool() -> dict:
    """
    Get current Android UI hierarchy for interaction analysis.

    Returns:
        Dictionary with UI elements, views, and their properties
    """
    try:
        return get_ui_state()
    except Exception as e:
        return {"error": f"Failed to get UI state: {str(e)}", "ui_elements": []}


@tool
def write_exploit_script(script_content: str) -> str:
    """
    Write the final exploit.sh script inside the container.

    Args:
        script_content: Full bash script content (must include #!/bin/bash header)

    Returns:
        Success or error message
    """
    try:
        # Ensure script has shebang
        if not script_content.startswith("#!/bin/bash"):
            script_content = "#!/bin/bash\n" + script_content

        # Escape content for shell
        script_escaped = script_content.replace("'", "'\\''")

        # Create directory and write file inside container
        cmd = f"mkdir -p /app/exploit_files && echo '{script_escaped}' > {CONTAINER_EXPLOIT_PATH} && chmod +x {CONTAINER_EXPLOIT_PATH}"
        execute_command_internal(cmd)

        return f"Successfully created exploit.sh at {CONTAINER_EXPLOIT_PATH}"
    except Exception as e:
        return f"Error writing exploit script: {str(e)}"
