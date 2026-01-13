"""
DiscEx Agent Tools - Tools for Discovery and Exploit phases.

All tools execute inside the kali-container for security isolation.
"""

import json
from typing import Any, Dict, Optional

from langchain_core.tools import tool

from agent.backend.docker_ops import execute_command_internal, get_ui_state
from agent.preprocessing.vector_store import get_vector_store

# Container paths
CONTAINER_CODEBASE_PATH = "/app/codebase"
CONTAINER_EXPLOIT_PATH = "/app/exploit_files/exploit.sh"

# Module-level CodeIndex storage (set by agent before running)
_code_index = None


def set_code_index(code_index) -> None:
    """Set the CodeIndex for tools to access."""
    global _code_index
    _code_index = code_index


# =============================================================================
# DISCOVERY TOOLS
# =============================================================================


@tool
def get_manifest_info() -> str:
    """
    Get Android manifest information including permissions, components, and exported items.

    Returns:
        JSON with package info, permissions, activities, services, receivers, providers,
        and which components are exported (accessible to other apps).
    """
    if _code_index is None:
        return json.dumps({"error": "CodeIndex not initialized"})

    return json.dumps({
        "package_name": _code_index.package_name,
        "permissions": _code_index.permissions,
        "activities": _code_index.activities,
        "services": _code_index.services,
        "receivers": _code_index.receivers,
        "providers": _code_index.providers,
        "exported_components": _code_index.exported_components,
        "entry_points": _code_index.entry_points,
    }, indent=2)


@tool
def get_code_structure() -> str:
    """
    Get code structure summary: class count, method count, sensitive API usage.

    Returns:
        JSON with code statistics and sensitive API categories found.
    """
    if _code_index is None:
        return json.dumps({"error": "CodeIndex not initialized"})

    # Summarize sensitive APIs by category
    api_summary: Dict[str, int] = {}
    for api in _code_index.sensitive_apis:
        cat = api.get("category", "unknown")
        api_summary[cat] = api_summary.get(cat, 0) + 1

    return json.dumps({
        "total_classes": len(_code_index.classes),
        "total_methods": len(_code_index.methods),
        "sensitive_api_summary": api_summary,
        "sensitive_api_count": len(_code_index.sensitive_apis),
    }, indent=2)


@tool
def get_sensitive_apis(category: Optional[str] = None, limit: int = 20) -> str:
    """
    Get sensitive API usages found in the codebase.

    Args:
        category: Filter by category (sql, crypto, webview, file, network, etc.). None for all.
        limit: Max number of results to return.

    Returns:
        JSON array of sensitive API calls with file, line, and category.
    """
    if _code_index is None:
        return json.dumps({"error": "CodeIndex not initialized"})

    apis = _code_index.sensitive_apis
    if category:
        apis = [a for a in apis if a.get("category") == category]

    return json.dumps(apis[:limit], indent=2)


@tool
def search_code_pattern(query: str, file_pattern: Optional[str] = None) -> str:
    """
    Fast regex search in the codebase using ripgrep.

    Args:
        query: Search pattern (supports regex)
        file_pattern: Optional file glob filter (e.g., '*.java', '*.kt')

    Returns:
        JSON array of matches with file, line, and text
    """
    query_escaped = query.replace("'", "'\\''")
    cmd = f"rg --json '{query_escaped}' {CONTAINER_CODEBASE_PATH}"

    if file_pattern:
        pattern_escaped = file_pattern.replace("'", "'\\''")
        cmd += f" --glob '{pattern_escaped}'"

    try:
        output = execute_command_internal(cmd)
        matches = []
        for line in output.split("\n"):
            if not line.strip() or line.startswith("Command:") or line.startswith("Output:"):
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    matches.append({
                        "file": data["data"]["path"]["text"],
                        "line": data["data"]["line_number"],
                        "text": data["data"]["lines"]["text"].strip(),
                    })
            except json.JSONDecodeError:
                continue

        return json.dumps(matches[:30], indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def semantic_search(query: str, top_k: int = 5) -> str:
    """
    Semantic search using vector embeddings to find code similar to the query.

    Args:
        query: Natural language query describing the code you're looking for
        top_k: Number of results to return

    Returns:
        JSON array of matching code chunks with file, text, and similarity score
    """
    vector_store = get_vector_store()

    try:
        results = vector_store.search(query, limit=top_k)
        formatted = [{
            "file": r.get("file_path", "unknown"),
            "text": r.get("text", "")[:500],
            "score": round(r.get("_distance", 0.0), 3),
            "line": r.get("start_line", 0),
        } for r in results]

        return json.dumps(formatted, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def read_source_file(file_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
    """
    Read source code file content.

    Args:
        file_path: Relative path from codebase root (e.g., 'src/MainActivity.java')
        start_line: Optional starting line number (1-indexed)
        end_line: Optional ending line number (1-indexed)

    Returns:
        File contents or specified line range
    """
    full_path = f"{CONTAINER_CODEBASE_PATH}/{file_path}"

    try:
        if start_line is not None and end_line is not None:
            cmd = f"sed -n '{start_line},{end_line}p' {full_path}"
        else:
            cmd = f"head -c 15000 {full_path}"

        output = execute_command_internal(cmd)

        if "Output:" in output:
            output = output.split("Output:", 1)[1].strip()

        return output if output else f"Error: Could not read file: {file_path}"
    except Exception as e:
        return f"Error reading file: {str(e)}"


# =============================================================================
# EXPLOIT TOOLS
# =============================================================================


@tool
def execute_adb_command(command: str) -> str:
    """
    Execute ADB or shell command for dynamic testing.

    Args:
        command: Shell command to execute (e.g., 'adb shell am start ...')

    Returns:
        Command output
    """
    try:
        return execute_command_internal(command)
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def get_ui_state_tool() -> Dict[str, Any]:
    """
    Get current Android UI hierarchy for interaction analysis.

    Returns:
        Dictionary with UI elements and their properties
    """
    try:
        return get_ui_state()
    except Exception as e:
        return {"error": str(e), "ui_elements": []}


@tool
def write_exploit_script(script_content: str) -> str:
    """
    Write the final exploit.sh script inside the container.

    Args:
        script_content: Full bash script content

    Returns:
        Success or error message
    """
    try:
        if not script_content.startswith("#!/bin/bash"):
            script_content = "#!/bin/bash\n" + script_content

        script_escaped = script_content.replace("'", "'\\''")
        cmd = f"mkdir -p /app/exploit_files && echo '{script_escaped}' > {CONTAINER_EXPLOIT_PATH} && chmod +x {CONTAINER_EXPLOIT_PATH}"
        execute_command_internal(cmd)

        return f"Successfully created exploit.sh at {CONTAINER_EXPLOIT_PATH}"
    except Exception as e:
        return f"Error: {str(e)}"


# Tool collections
DISCOVERY_TOOLS = [
    get_manifest_info,
    get_code_structure,
    get_sensitive_apis,
    search_code_pattern,
    semantic_search,
    read_source_file,
]

EXPLOIT_TOOLS = [
    execute_adb_command,
    get_ui_state_tool,
    write_exploit_script,
]
