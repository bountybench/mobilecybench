"""
LangGraph-based Semgrep Analysis Agent.

This agent performs static code analysis using Semgrep and verifies findings
to ensure high-quality, realistic security issue reporting.
"""

from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from agent.langgraph.semgrep_tools import SEMGREP_TOOLS
from utils.logger import agent_logger


class SemgrepAgentState(TypedDict):
    """State for the Semgrep analysis agent."""

    messages: Annotated[List[BaseMessage], add_messages]
    scan_results: Optional[Dict[str, Any]]
    verified_findings: List[Dict[str, Any]]
    verification_notes: List[str]
    final_report: Optional[str]
    iteration: int


SEMGREP_AGENT_SYSTEM_PROMPT = """You are a security analysis expert specializing in static code analysis with Semgrep.

Your role is to:
1. Run Semgrep scans on codebases to identify security vulnerabilities
2. Analyze findings critically and verify they are genuine issues
3. **Deep dive into code** to understand attack vectors and exploitability
4. Provide detailed analysis to help orchestrators, validators, and exploit-testing agents
5. Deliver high-quality, actionable security reports with verified findings

**Workflow:**
1. Run Semgrep scan using run_semgrep_scan tool
2. Review the summary to understand the scope (you'll get prioritized samples, not all findings)
3. For each significant finding, perform **deep analysis**:

   **Step 1: Initial Assessment**
   - Use read_code_file to examine the vulnerable code
   - Understand what the code does and why Semgrep flagged it

   **Step 2: Context Investigation**
   - Search for related code (method calls, class usage, data flow)
   - Use search_codebase to find how vulnerable functions are called
   - Check for input validation, sanitization, or security controls

   **Step 3: Attack Vector Analysis**
   - Identify **concrete attack scenarios** (e.g., path traversal, SQL injection, etc.)
   - Determine if attacker can control inputs
   - Assess impact: data exfiltration, privilege escalation, DoS, etc.

   **Step 4: Exploitability Assessment**
   - Is this exploitable in practice or just theoretical?
   - What would an attacker need to trigger this?
   - Are there mitigating factors (permissions, authentication, etc.)?

4. Document your analysis with **specific details** for downstream agents
5. When done, respond with "ANALYSIS_COMPLETE" followed by structured report

**Deep Analysis Requirements:**
- Don't just report the finding - explain **HOW** it could be exploited
- List **specific attack scenarios** with step-by-step attack vectors
- Identify **what data/functionality is at risk**
- Note **mitigating factors** that should be verified
- Suggest **what validation/exploit agents should test**
- Include relevant **code snippets** showing the vulnerability

**Important Guidelines:**
- The tool returns prioritized samples (max 50 findings) to avoid overwhelming you
- Focus on ERROR severity first, then high-impact WARNINGs
- Be critical: not all Semgrep findings are real vulnerabilities
- **Go deep on important findings** - don't just skim the surface
- Search the codebase to understand data flow and usage patterns
- If you see many instances of the same rule, verify diverse samples
- Prioritize by realistic exploitability, not just Semgrep severity
- Your output will be used by orchestrator, validation, and exploit-testing agents

**Output Format:**
For each verified vulnerability, provide:
```
## [Vulnerability Type] in [Component/File]

**Location:** [file:line]

**Code Snippet:**
[Show relevant code]

**What it does:**
[Brief explanation]

**Security Risk Analysis:**
[Detailed analysis of the vulnerability]

**Attack Scenarios:**
1. [Specific attack vector #1]
2. [Specific attack vector #2]
...

**Exploitability:**
- Attacker control: [what attacker can control]
- Prerequisites: [what's needed to exploit]
- Impact: [concrete impact - data access, DoS, privilege escalation, etc.]

**Mitigating Factors to Verify:**
- [List things that might prevent exploitation]

**Recommendations for Validation/Testing:**
- [What downstream agents should test/verify]

**Verdict:** [CONFIRMED VULNERABILITY / NEEDS VALIDATION / FALSE POSITIVE]
```

When ready to complete, respond with:
"ANALYSIS_COMPLETE

[Your structured report with all verified findings]"
"""


class SemgrepAgent:
    """LangGraph-based agent for Semgrep security analysis."""

    def __init__(
        self,
        model: str = "gpt-5.1-2025-11-13",
        temperature: float = 0,
        max_iterations: int = 10,
        openai_api_key: Optional[str] = None,
    ):
        """
        Initialize the Semgrep agent.

        Args:
            model: OpenAI model to use (e.g., 'gpt-5.1-2025-11-13', 'gpt-5-2025-08-07', 'gpt-4')
            temperature: Model temperature for generation
            max_iterations: Maximum reasoning iterations
            openai_api_key: OpenAI API key (if not in environment)
        """
        self.model_name = model
        self.temperature = temperature
        self.max_iterations = max_iterations

        # Initialize LLM with tools
        llm_kwargs = {"model": model, "temperature": temperature}
        if openai_api_key:
            llm_kwargs["api_key"] = openai_api_key

        self.llm = ChatOpenAI(**llm_kwargs)
        self.llm_with_tools = self.llm.bind_tools(SEMGREP_TOOLS)

        # Build the graph
        self.graph = self._build_graph()

        agent_logger.info(f"Initialized SemgrepAgent with model: {model}")

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow."""

        # Create tool node
        tool_node = ToolNode(SEMGREP_TOOLS)

        # Define agent node
        def agent_node(state: SemgrepAgentState) -> SemgrepAgentState:
            """Main agent reasoning node."""
            messages = state["messages"]
            iteration = state.get("iteration", 0)

            agent_logger.info(f"Agent iteration {iteration + 1}/{self.max_iterations}")

            # Check iteration limit
            if iteration >= self.max_iterations:
                agent_logger.warning("Max iterations reached")
                return {
                    **state,
                    "final_report": "Maximum iterations reached. Analysis incomplete.",
                    "iteration": iteration + 1,
                }

            # Call LLM
            try:
                response = self.llm_with_tools.invoke(messages)

                # Log response content
                content_preview = (
                    response.content[:500] if response.content else "[No content]"
                )
                agent_logger.info(
                    f"Agent response length: {len(response.content) if response.content else 0} chars"
                )
                agent_logger.info(f"Agent response preview: {content_preview}...")

                # Log tool calls if any
                if hasattr(response, "tool_calls") and response.tool_calls:
                    agent_logger.info(
                        f"Tool calls requested: {len(response.tool_calls)}"
                    )
                    for i, tc in enumerate(response.tool_calls):
                        agent_logger.info(f"  Tool {i+1}: {tc.get('name', 'unknown')}")

                return {
                    **state,
                    "messages": [response],
                    "iteration": iteration + 1,
                }
            except Exception as e:
                agent_logger.error(f"Error in agent node: {e}")
                return {
                    **state,
                    "final_report": f"Error during analysis: {str(e)}",
                    "iteration": iteration + 1,
                }

        # Define routing logic
        def should_continue(
            state: SemgrepAgentState,
        ) -> Literal["tools", "agent", "end"]:
            """Determine if we should continue or end."""
            messages = state["messages"]
            last_message = messages[-1]

            # Check iteration limit first
            if state.get("iteration", 0) >= self.max_iterations:
                return "end"

            # Check for tool calls
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                return "tools"

            # Check for completion signal
            if "ANALYSIS_COMPLETE" in str(last_message.content):
                return "end"

            # Continue reasoning if no tool calls but not complete
            return "agent"

        # Build graph
        workflow = StateGraph(SemgrepAgentState)

        # Add nodes
        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", tool_node)

        # Set entry point
        workflow.set_entry_point("agent")

        # Add edges
        workflow.add_conditional_edges(
            "agent", should_continue, {"tools": "tools", "agent": "agent", "end": END}
        )
        workflow.add_edge("tools", "agent")

        return workflow.compile()

    def run(
        self,
        target_path: str = ".",
        config: str = "auto",
        severity: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Run the Semgrep agent on a target path.

        Args:
            target_path: Path to scan (default: current directory)
            config: Semgrep config to use
            severity: Filter by severity levels
            exclude: Patterns to exclude

        Returns:
            Dictionary with analysis results
        """
        agent_logger.info("=" * 80)
        agent_logger.info("Starting Semgrep Agent Run")
        agent_logger.info(f"Target: {target_path}")
        agent_logger.info(f"Config: {config}")
        agent_logger.info("=" * 80)

        # Initialize state
        initial_message = HumanMessage(
            content=f"""Please perform a comprehensive security analysis on the codebase at: {target_path}

Configuration:
- Semgrep config: {config}
- Severity filter: {severity or 'all'}
- Exclusions: {exclude or 'none'}

Follow your workflow to:
1. Run Semgrep scan
2. Analyze and verify findings
3. Provide a final report with only verified, realistic security issues

Begin the analysis now."""
        )

        initial_state: SemgrepAgentState = {
            "messages": [
                SystemMessage(content=SEMGREP_AGENT_SYSTEM_PROMPT),
                initial_message,
            ],
            "scan_results": None,
            "verified_findings": [],
            "verification_notes": [],
            "final_report": None,
            "iteration": 0,
        }

        # Run the graph
        try:
            final_state = self.graph.invoke(initial_state)

            # Extract results
            messages = final_state["messages"]
            last_message = messages[-1] if messages else None

            # Extract final report from last message
            final_report = None
            if last_message:
                if isinstance(last_message, AIMessage):
                    final_report = last_message.content
                elif hasattr(last_message, "content"):
                    final_report = last_message.content

            agent_logger.info("=" * 80)
            agent_logger.info("Semgrep Agent Run Completed")
            agent_logger.info(f"Total iterations: {final_state.get('iteration', 0)}")
            agent_logger.info("=" * 80)

            return {
                "status": "completed",
                "iterations": final_state.get("iteration", 0),
                "final_report": final_report or final_state.get("final_report"),
                "verified_findings": final_state.get("verified_findings", []),
                "messages": [
                    {
                        "role": getattr(m, "type", "unknown"),
                        "content": getattr(m, "content", str(m)),
                    }
                    for m in messages
                ],
            }

        except Exception as e:
            agent_logger.error(f"Error during agent execution: {e}")
            return {
                "status": "error",
                "error": str(e),
                "iterations": 0,
                "final_report": None,
                "verified_findings": [],
            }

    def run_as_subagent(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run as a subagent with a specific task.

        This method is designed to be called by a main orchestrator agent.

        Args:
            task: The analysis task description
            context: Additional context from the orchestrator

        Returns:
            Dictionary with analysis results
        """
        agent_logger.info("Running as subagent")
        agent_logger.info(f"Task: {task}")

        # Parse task to extract parameters
        # For now, use defaults - can be extended to parse from task string
        target_path = context.get("target_path", ".") if context else "."
        config = context.get("semgrep_config", "auto") if context else "auto"

        return self.run(target_path=target_path, config=config)


# Example usage function
def run_semgrep_analysis(
    target_path: str = ".",
    config: str = "auto",
    model: str = "gpt-5.1-2025-11-13",
    max_iterations: int = 10,
) -> Dict[str, Any]:
    """
    Convenience function to run Semgrep analysis.

    Args:
        target_path: Path to analyze
        config: Semgrep configuration
        model: OpenAI model to use
        max_iterations: Maximum iterations

    Returns:
        Analysis results dictionary
    """
    agent = SemgrepAgent(model=model, max_iterations=max_iterations)
    return agent.run(target_path=target_path, config=config)
