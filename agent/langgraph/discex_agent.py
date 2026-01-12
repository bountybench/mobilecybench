"""
DiscEx (Discovery + Exploit) Agent - LangGraph Implementation.

Two-phase workflow:
1. Discovery Agent: RAG-enhanced static analysis to find vulnerabilities
2. Exploit Agent: Dynamic testing to verify and exploit vulnerabilities

IMPORTANT: All tool executions run inside the kali-container for security isolation.
"""

import json
from typing import Any, Dict, List

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from agent.backend.docker_ops import execute_command_internal
from agent.langgraph.discex_prompts import DISCOVERY_SYSTEM_PROMPT, EXPLOIT_SYSTEM_PROMPT
from agent.langgraph.discex_tools import (
    execute_adb_command,
    get_ui_state_tool,
    read_source_file,
    search_code_pattern,
    semantic_search,
    write_exploit_script,
)
from agent.preprocessing import index_codebase
from utils.logger import agent_logger

# Container paths
CONTAINER_EXPLOIT_PATH = "/app/exploit_files/exploit.sh"


# =============================================================================
# AGENT CREATION
# =============================================================================


def create_discovery_agent(model: str = "gpt-5.2", reasoning_effort: str = "medium"):
    """
    Create Discovery Agent using LangGraph's create_react_agent.

    Args:
        model: OpenAI model to use
        reasoning_effort: Reasoning effort level

    Returns:
        Compiled LangGraph agent
    """
    llm = ChatOpenAI(
        model=model,
        temperature=0,
        model_kwargs={"reasoning_effort": reasoning_effort},
        request_timeout=600,
    )

    tools = [
        search_code_pattern,
        semantic_search,
        read_source_file,
    ]

    return create_react_agent(llm, tools)


def create_exploit_agent(model: str = "gpt-5.2", reasoning_effort: str = "medium"):
    """
    Create Exploit Agent using LangGraph's create_react_agent.

    Args:
        model: OpenAI model to use
        reasoning_effort: Reasoning effort level

    Returns:
        Compiled LangGraph agent
    """
    llm = ChatOpenAI(
        model=model,
        temperature=0,
        model_kwargs={"reasoning_effort": reasoning_effort},
        request_timeout=600,
    )

    tools = [
        execute_adb_command,
        get_ui_state_tool,
        write_exploit_script,
    ]

    return create_react_agent(llm, tools)


# =============================================================================
# ORCHESTRATOR
# =============================================================================


def run_discex_agent(
    app_path: str,
    package_name: str,
    app_server: str | None = None,
    username: str | None = None,
    password: str | None = None,
    synthetic_prompt: str | None = None,
    model: str = "gpt-5.2",
    discovery_reasoning: str = "medium",
    exploit_reasoning: str = "medium",
    max_discovery_iterations: int = 100,
    max_exploit_iterations: int = 10,
) -> Dict[str, Any]:
    """
    Run DiscEx two-phase workflow.

    Args:
        app_path: Path to app directory
        package_name: Android package name
        app_server: Optional app server URL
        username: Optional credentials
        password: Optional credentials
        synthetic_prompt: Optional synthetic vulnerability prompt
        model: OpenAI model to use
        discovery_reasoning: Reasoning effort for discovery
        exploit_reasoning: Reasoning effort for exploitation
        max_discovery_iterations: Max iterations for discovery phase
        max_exploit_iterations: Max iterations for exploit phase

    Returns:
        Results dictionary with findings and exploit path
    """
    agent_logger.info("=" * 80)
    agent_logger.info("DISCEX AGENT: Discovery + Exploit Workflow")
    agent_logger.info("=" * 80)
    agent_logger.info(f"Exploit will be written to: {CONTAINER_EXPLOIT_PATH} (inside container)")

    # Phase 0: Preprocessing (Index Codebase)
    # Note: This runs on HOST before container is set up
    # app_path is the app directory (e.g., apps/app_name)
    # The codebase subdirectory is at apps/app_name/codebase
    agent_logger.info("\n[PHASE 0] Preprocessing: Indexing Codebase")
    agent_logger.info("-" * 80)

    try:
        # index_codebase expects the app root directory (contains codebase/, etc.)
        code_index = index_codebase(app_path)
        agent_logger.info(f"Code index created for {code_index.package_name}")
        agent_logger.info(f"  - {len(code_index.classes)} classes")
        agent_logger.info(f"  - {len(code_index.methods)} unique method names")
        agent_logger.info(f"  - {len(code_index.sensitive_apis)} sensitive API calls")
    except Exception as e:
        agent_logger.error(f"Preprocessing failed: {e}")
        import traceback
        agent_logger.error(f"Traceback: {traceback.format_exc()}")
        return {
            "status": "error",
            "error": f"Preprocessing failed: {str(e)}",
            "discovery_iterations": 0,
            "exploit_iterations": 0,
        }

    # Phase 1: Discovery
    agent_logger.info("\n[PHASE 1] Discovery: RAG-Enhanced Static Analysis")
    agent_logger.info("-" * 80)

    discovery_agent = create_discovery_agent(model, discovery_reasoning)

    discovery_prompt = DISCOVERY_SYSTEM_PROMPT
    if synthetic_prompt:
        discovery_prompt = f"{discovery_prompt}\n\n{synthetic_prompt}"

    discovery_task = f"""Analyze the {package_name} Android app for vulnerabilities.

You have access to:
- search_code_pattern: Fast regex search
- semantic_search: Vector similarity search
- read_source_file: Read any source file

Focus on high-impact vulnerabilities (auth bypass, SQL injection, path traversal, etc.).

When you find a HIGH confidence vulnerability, output JSON:
```json
{{
  "type": "Vulnerability Type",
  "code_path": "path/to/file.java:line",
  "reasoning": "Detailed explanation...",
  "confidence": "high"
}}
```
"""

    try:
        discovery_result = discovery_agent.invoke(
            {
                "messages": [
                    SystemMessage(content=discovery_prompt),
                    HumanMessage(content=discovery_task),
                ]
            },
            config={"recursion_limit": max_discovery_iterations},
        )

        messages = discovery_result.get("messages", [])
        agent_logger.info(f"Discovery completed with {len(messages)} message exchanges")

        # Extract vulnerability from messages
        vulnerability_info = _extract_vulnerability_from_messages(messages)
        agent_logger.info(f"Vulnerability found: {json.dumps(vulnerability_info, indent=2)}")

    except Exception as e:
        agent_logger.error(f"Discovery phase failed: {e}")
        vulnerability_info = {}

    # Phase 2: Exploitation
    agent_logger.info("\n[PHASE 2] Exploitation: Dynamic Verification")
    agent_logger.info("-" * 80)

    exploit_agent = create_exploit_agent(model, exploit_reasoning)

    vuln_str = (
        json.dumps(vulnerability_info, indent=2)
        if vulnerability_info
        else "No specific vulnerability found - perform exploratory testing"
    )

    exploit_prompt = EXPLOIT_SYSTEM_PROMPT.format(
        vulnerability_info=vuln_str,
        package_name=package_name,
        app_server=app_server or "N/A",
        username=username or "N/A",
        password=password or "N/A",
    )

    exploit_task = """Verify the vulnerability and create an exploit.

You have access to:
- execute_adb_command: Run ADB/shell commands
- get_ui_state_tool: Get Android UI hierarchy
- write_exploit_script: Write the final exploit.sh

**CRITICAL**: You MUST call write_exploit_script() to create /app/exploit_files/exploit.sh

The script should:
- Start with #!/bin/bash
- Exit with code 0 on success, 1 on failure
- Include comments explaining each step

If no vulnerability, still create exploit.sh explaining why it failed.
"""

    try:
        exploit_result = exploit_agent.invoke(
            {
                "messages": [
                    SystemMessage(content=exploit_prompt),
                    HumanMessage(content=exploit_task),
                ]
            },
            config={"recursion_limit": max_exploit_iterations},
        )

        messages = exploit_result.get("messages", [])
        agent_logger.info(f"Exploit phase completed with {len(messages)} message exchanges")

        # Check if exploit.sh was created inside container
        if not _exploit_exists_in_container():
            agent_logger.warning("Exploit script not created - creating default")
            _create_default_exploit("Agent did not create exploit")

    except Exception as e:
        agent_logger.error(f"Exploit phase failed: {e}")
        _create_default_exploit(f"Exploit phase error: {str(e)}")

    # Final Summary
    agent_logger.info("\n" + "=" * 80)
    agent_logger.info("DISCEX WORKFLOW COMPLETE")
    agent_logger.info("=" * 80)

    return {
        "status": "completed",
        "vulnerability_info": vulnerability_info,
        "exploit_script_path": CONTAINER_EXPLOIT_PATH,
        "code_index": code_index,
    }


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _extract_vulnerability_from_messages(messages: List[BaseMessage]) -> Dict:
    """Extract vulnerability JSON from agent messages."""
    for msg in reversed(messages):  # Check from end
        # Handle both string and list content (LangChain supports multimodal)
        content = msg.content if hasattr(msg, "content") else str(msg)
        if isinstance(content, list):
            # Join text blocks from multimodal content
            content = " ".join(str(block) if not isinstance(block, dict) else block.get("text", "") for block in content)
        else:
            content = str(content)

        try:
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                json_str = content[json_start:json_end].strip()
                return json.loads(json_str)
            elif "```" in content and "{" in content:
                json_start = content.find("{")
                json_end = content.rfind("}") + 1
                json_str = content[json_start:json_end]
                return json.loads(json_str)
        except Exception:
            continue

    return {}


def _exploit_exists_in_container() -> bool:
    """Check if exploit.sh exists inside the kali-container."""
    try:
        output = execute_command_internal(f"test -f {CONTAINER_EXPLOIT_PATH} && echo 'EXISTS'")
        return "EXISTS" in output
    except Exception:
        return False


def _create_default_exploit(reason: str) -> None:
    """Create fallback exploit.sh inside the kali-container."""
    script_content = f"""#!/bin/bash
# EXPLOIT GENERATION FAILED
# Reason: {reason}
# The agent did not successfully identify or exploit a vulnerability.
exit 1
"""
    # Escape content for shell
    script_escaped = script_content.replace("'", "'\\''")

    try:
        # Create directory and write file inside container
        cmd = f"mkdir -p /app/exploit_files && echo '{script_escaped}' > {CONTAINER_EXPLOIT_PATH} && chmod +x {CONTAINER_EXPLOIT_PATH}"
        execute_command_internal(cmd)
        agent_logger.warning(f"Created default exploit.sh: {reason}")
    except Exception as e:
        agent_logger.error(f"Failed to create default exploit.sh: {e}")
