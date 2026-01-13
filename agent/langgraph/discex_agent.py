"""
DiscEx (Discovery + Exploit) Agent - LangGraph StateGraph Implementation.

Graph-driven two-phase workflow:
1. Discovery Node: Finds vulnerabilities using CodeIndex tools + code search
2. Exploit Node(s): Creates proof-of-concept exploits (parallel via Send API)

All tool executions run inside the kali-container for security isolation.
"""

import json
from dataclasses import dataclass
from typing import Annotated, Any, Dict, List, Sequence

from langchain.agents import create_agent
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agent.backend.docker_ops import execute_command_internal
from agent.langgraph.discex_context import VulnerabilityFinding
from agent.langgraph.discex_prompts import build_discovery_prompt, build_exploit_prompt
from agent.langgraph.discex_tools import (
    DISCOVERY_TOOLS,
    EXPLOIT_TOOLS,
    set_code_index,
)
from agent.preprocessing import index_codebase
from utils.logger import agent_logger

CONTAINER_EXPLOIT_PATH = "/app/exploit_files/exploit.sh"


# =============================================================================
# STATE SCHEMA
# =============================================================================


@dataclass
class ExploitAttempt:
    """Result of a single exploit attempt."""
    vulnerability: VulnerabilityFinding | None
    success: bool = False
    message_count: int = 0
    error: str | None = None


def _merge_exploit_results(left: List[ExploitAttempt], right: List[ExploitAttempt]) -> List[ExploitAttempt]:
    """Reducer: merge exploit results from parallel Send operations."""
    return left + right


class DiscExState(Dict):
    """
    Shared state for the DiscEx workflow.

    Uses TypedDict-like structure with reducers for proper state management.
    """
    # Input configuration
    app_path: str
    package_name: str
    app_server: str | None
    username: str | None
    password: str | None
    synthetic_prompt: str | None
    model: str
    max_discovery_iterations: int
    max_exploit_iterations: int

    # Discovery outputs
    code_index: Any  # CodeIndex object
    vulnerability_findings: List[VulnerabilityFinding]
    discovery_messages: List[BaseMessage]

    # Exploitation outputs (uses reducer for parallel merging)
    exploit_results: Annotated[List[ExploitAttempt], _merge_exploit_results]
    successful_exploit: bool

    # Final status
    status: str
    error: str | None


# =============================================================================
# NODE FUNCTIONS
# =============================================================================


def index_codebase_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Node: Index the codebase and make CodeIndex available to tools."""
    agent_logger.info("[NODE] Indexing Codebase")

    try:
        code_index = index_codebase(state["app_path"])
        set_code_index(code_index)  # Make available to discovery tools

        agent_logger.info(f"  Package: {code_index.package_name}")
        agent_logger.info(f"  Classes: {len(code_index.classes)}")
        agent_logger.info(f"  Sensitive APIs: {len(code_index.sensitive_apis)}")

        return {
            "code_index": code_index,
            "status": "indexed",
        }

    except Exception as e:
        agent_logger.error(f"  Indexing failed: {e}")
        return {
            "status": "error",
            "error": str(e),
        }


def discovery_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Node: Run Discovery Agent to find vulnerabilities."""
    agent_logger.info("[NODE] Discovery")

    if state.get("status") == "error":
        return {}  # Skip if previous node failed

    model = state.get("model", "gpt-4o")
    max_iterations = state.get("max_discovery_iterations", 100)
    synthetic_prompt = state.get("synthetic_prompt")

    # Build prompt and task
    discovery_prompt = build_discovery_prompt(synthetic_prompt)
    discovery_task = f"Analyze {state['package_name']} for security vulnerabilities. Output each finding as JSON."

    # Create discovery agent (LangChain v1 create_agent)
    llm = ChatOpenAI(model=model, temperature=0, request_timeout=600)
    discovery_agent = create_agent(
        model=llm,
        tools=DISCOVERY_TOOLS,
        system_prompt=discovery_prompt,
    )

    try:
        result = discovery_agent.invoke(
            {"messages": [HumanMessage(content=discovery_task)]},
            config={"recursion_limit": max_iterations},
        )

        messages = result.get("messages", [])
        findings = _extract_vulnerability_findings(messages)

        agent_logger.info(f"  Found {len(findings)} vulnerabilities")
        for i, f in enumerate(findings, 1):
            agent_logger.info(f"    [{i}] {f.vuln_type} ({f.severity}, {f.confidence:.0%})")

        return {
            "vulnerability_findings": findings,
            "discovery_messages": messages,
            "status": "discovered",
        }

    except Exception as e:
        agent_logger.error(f"  Discovery failed: {e}")
        return {
            "vulnerability_findings": [],
            "discovery_messages": [],
            "status": "discovery_failed",
            "error": str(e),
        }


def route_to_exploits(state: Dict[str, Any]) -> Sequence[Send]:
    """
    Conditional edge: Fan out to parallel exploit attempts using Send API.

    Each vulnerability gets its own exploit attempt, running in parallel.
    If no vulnerabilities found, sends one exploratory attempt.
    """
    findings = state.get("vulnerability_findings", [])

    if not findings:
        # No findings - send exploratory attempt
        agent_logger.info("[ROUTE] No vulnerabilities - sending exploratory exploit")
        return [Send("exploit_node", {**state, "_exploit_target": None})]

    # Fan out to parallel exploit attempts
    agent_logger.info(f"[ROUTE] Sending {len(findings)} parallel exploit attempts")
    return [
        Send("exploit_node", {**state, "_exploit_target": finding})
        for finding in findings
    ]


def exploit_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Node: Run Exploit Agent for a single vulnerability.

    This node is invoked in parallel via Send API for each vulnerability.
    """
    finding = state.get("_exploit_target")
    vuln_name = finding.vuln_type if finding else "exploratory"
    agent_logger.info(f"[NODE] Exploit: {vuln_name}")

    model = state.get("model", "gpt-4o")
    max_iterations = state.get("max_exploit_iterations", 50)

    # Build vulnerability context
    if finding is None:
        vuln_context = "No specific vulnerability found. Test exported components and common issues."
    else:
        vuln_context = finding.to_exploit_context()

    exploit_prompt = build_exploit_prompt(
        vulnerability_context=vuln_context,
        package_name=state["package_name"],
        app_server=state.get("app_server"),
        username=state.get("username"),
        password=state.get("password"),
    )

    exploit_task = "Create a working exploit. MUST call write_exploit_script() to save exploit.sh."

    # Create exploit agent (LangChain v1 create_agent)
    llm = ChatOpenAI(model=model, temperature=0, request_timeout=600)
    exploit_agent = create_agent(
        model=llm,
        tools=EXPLOIT_TOOLS,
        system_prompt=exploit_prompt,
    )

    try:
        result = exploit_agent.invoke(
            {"messages": [HumanMessage(content=exploit_task)]},
            config={"recursion_limit": max_iterations},
        )

        messages = result.get("messages", [])
        success = _exploit_exists()

        if success:
            agent_logger.info(f"  SUCCESS: exploit.sh created for {vuln_name}")

        attempt = ExploitAttempt(
            vulnerability=finding,
            success=success,
            message_count=len(messages),
        )

        return {"exploit_results": [attempt]}

    except Exception as e:
        agent_logger.error(f"  Exploit failed: {e}")
        attempt = ExploitAttempt(
            vulnerability=finding,
            success=False,
            error=str(e),
        )
        return {"exploit_results": [attempt]}


def finalize_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Node: Finalize results, create default exploit if none succeeded."""
    agent_logger.info("[NODE] Finalize")

    exploit_results = state.get("exploit_results", [])
    successful = any(r.success for r in exploit_results)

    if not successful and not _exploit_exists():
        _create_default_exploit("No successful exploit")

    agent_logger.info(f"  Vulnerabilities: {len(state.get('vulnerability_findings', []))}")
    agent_logger.info(f"  Exploit attempts: {len(exploit_results)}")
    agent_logger.info(f"  Successful: {successful}")

    return {
        "successful_exploit": successful,
        "status": "completed",
    }


# =============================================================================
# GRAPH CONSTRUCTION
# =============================================================================


def build_discex_graph() -> StateGraph:
    """
    Build the DiscEx StateGraph.

    Graph structure:
        START -> index -> discovery -> [parallel exploit attempts] -> finalize -> END
    """
    builder = StateGraph(dict)

    # Add nodes
    builder.add_node("index", index_codebase_node)
    builder.add_node("discovery", discovery_node)
    builder.add_node("exploit_node", exploit_node)
    builder.add_node("finalize", finalize_node)

    # Add edges
    builder.add_edge(START, "index")
    builder.add_edge("index", "discovery")

    # Conditional edge: fan out to parallel exploits
    builder.add_conditional_edges("discovery", route_to_exploits, ["exploit_node"])

    # All exploit attempts converge to finalize
    builder.add_edge("exploit_node", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def run_discex_agent(
    app_path: str,
    package_name: str,
    app_server: str | None = None,
    username: str | None = None,
    password: str | None = None,
    synthetic_prompt: str | None = None,
    model: str = "gpt-4o",
    discovery_reasoning: str = "medium",  # Kept for API compatibility
    exploit_reasoning: str = "medium",    # Kept for API compatibility
    max_discovery_iterations: int = 100,
    max_exploit_iterations: int = 50,
) -> Dict[str, Any]:
    """
    Run DiscEx workflow using LangGraph StateGraph.

    Returns:
        Results dictionary with findings and exploit path
    """
    agent_logger.info("=" * 60)
    agent_logger.info("DISCEX AGENT (StateGraph)")
    agent_logger.info("=" * 60)

    # Build and compile the graph
    graph = build_discex_graph()

    # Initial state
    initial_state = {
        "app_path": app_path,
        "package_name": package_name,
        "app_server": app_server,
        "username": username,
        "password": password,
        "synthetic_prompt": synthetic_prompt,
        "model": model,
        "max_discovery_iterations": max_discovery_iterations,
        "max_exploit_iterations": max_exploit_iterations,
        "vulnerability_findings": [],
        "discovery_messages": [],
        "exploit_results": [],
        "successful_exploit": False,
        "status": "starting",
        "error": None,
        "code_index": None,
    }

    # Run the graph
    final_state = graph.invoke(initial_state)

    # Format results
    return {
        "status": final_state.get("status", "unknown"),
        "error": final_state.get("error"),
        "vulnerability_findings": [
            f.to_dict() for f in final_state.get("vulnerability_findings", [])
        ],
        "exploitation_results": [
            {
                "vulnerability": r.vulnerability.to_dict() if r.vulnerability else None,
                "success": r.success,
                "message_count": r.message_count,
                "error": r.error,
            }
            for r in final_state.get("exploit_results", [])
        ],
        "successful_exploit": final_state.get("successful_exploit", False),
        "exploit_script_path": CONTAINER_EXPLOIT_PATH,
        "code_index": final_state.get("code_index"),
    }


# =============================================================================
# HELPERS
# =============================================================================


def _extract_vulnerability_findings(messages: List[BaseMessage]) -> List[VulnerabilityFinding]:
    """Extract vulnerability findings from agent messages."""
    findings: List[VulnerabilityFinding] = []
    seen: set = set()

    for msg in messages:
        content = msg.content if hasattr(msg, "content") else str(msg)
        if isinstance(content, list):
            content = " ".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in content)

        for json_data in _extract_json_blocks(str(content)):
            if "vuln_type" not in json_data:
                continue

            key = (json_data.get("vuln_type"), json_data.get("entry_point", ""))
            if key in seen:
                continue
            seen.add(key)

            findings.append(VulnerabilityFinding(
                vuln_type=json_data.get("vuln_type", "Unknown"),
                severity=json_data.get("severity", "medium"),
                confidence=float(json_data.get("confidence", 0.5)),
                entry_point=json_data.get("entry_point", ""),
                data_flow=json_data.get("data_flow", []),
                vulnerable_sink=json_data.get("vulnerable_sink", ""),
                code_locations=json_data.get("code_locations", []),
                prerequisites=json_data.get("prerequisites", []),
                attack_vector=json_data.get("attack_vector", ""),
                payload_hints=json_data.get("payload_hints", []),
            ))

    findings.sort(key=lambda f: f.confidence, reverse=True)
    return findings


def _extract_json_blocks(content: str) -> List[Dict[str, Any]]:
    """Extract JSON objects from content."""
    results: List[Dict[str, Any]] = []

    # Find ```json blocks
    remaining = content
    while "```json" in remaining:
        start = remaining.find("```json") + 7
        end = remaining.find("```", start)
        if end == -1:
            break
        try:
            data = json.loads(remaining[start:end].strip())
            if isinstance(data, dict):
                results.append(data)
        except json.JSONDecodeError:
            pass
        remaining = remaining[end + 3:]

    # Try raw JSON if no blocks found
    if not results and "{" in content:
        depth = 0
        start_idx = None
        for i, c in enumerate(content):
            if c == "{":
                if depth == 0:
                    start_idx = i
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0 and start_idx is not None:
                    try:
                        data = json.loads(content[start_idx:i + 1])
                        if isinstance(data, dict):
                            results.append(data)
                    except json.JSONDecodeError:
                        pass
                    start_idx = None

    return results


def _exploit_exists() -> bool:
    """Check if exploit.sh exists in container."""
    try:
        output = execute_command_internal(f"test -f {CONTAINER_EXPLOIT_PATH} && echo EXISTS")
        return "EXISTS" in output
    except Exception:
        return False


def _create_default_exploit(reason: str) -> None:
    """Create fallback exploit.sh in container."""
    script = f"#!/bin/bash\n# {reason}\nexit 1"
    escaped = script.replace("'", "'\\''")
    try:
        execute_command_internal(f"mkdir -p /app/exploit_files && echo '{escaped}' > {CONTAINER_EXPLOIT_PATH} && chmod +x {CONTAINER_EXPLOIT_PATH}")
    except Exception as e:
        agent_logger.error(f"Failed to create default exploit: {e}")
