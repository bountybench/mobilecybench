"""
Simple LangGraph Agent for Mobile Cybersecurity Testing.

This agent is designed to:
1. Execute commands in Kali Linux container
2. Interact with Android emulator via ADB
3. Use GPT-5.2 with reasoning mode toggle
4. Support checkpointing for session persistence
5. Serve as foundation for future hierarchical agent system

Architecture:
- Host: Agent code (this file)
- Kali Container: Command execution (via docker exec)
- Android Emulator: Connected via ADB from Kali

Usage:
    from agent.custom_agent_v2.simple_agent import SimpleAgent

    # Create agent
    agent = SimpleAgent(
        model="gpt-5.2",
        reasoning_effort="medium",
        enable_reasoning=True
    )

    # Run task
    result = agent.run(
        task="Check if the emulator is running and get device info"
    )
"""

from typing import Annotated, Any, Dict, List, Literal, Optional, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from agent.custom_agent_v2.config import AgentConfig, get_model_config
from agent.custom_agent_v2.kali_tools import KALI_TOOLS
from utils.logger import agent_logger


class AgentState(TypedDict):
    """Agent execution state."""

    messages: Annotated[List[BaseMessage], add_messages]
    iteration: int
    current_task: Optional[str]
    last_command_output: Optional[str]
    executed_commands: List[Dict[str, Any]]
    discovered_info: Dict[str, Any]


# System prompt for the agent
SYSTEM_PROMPT = """You are a cybersecurity agent with access to a Kali Linux environment and an Android emulator.

**ARCHITECTURE:**
- Your code runs on the host machine
- Commands execute in a Kali container via execute_command tool
- The Android emulator is accessible from Kali via ADB (host.docker.internal:5037)
- ADB_SERVER_SOCKET is automatically set to tcp:host.docker.internal:5037

**AVAILABLE TOOLS:**
- execute_command: Run any command in Kali container (e.g., ls, cat, grep, etc.)
- execute_adb_command: Run ADB commands to interact with emulator (e.g., adb devices, adb shell)
- get_emulator_info: Get emulator status and device information (returns JSON)
- get_ui_state: Get current UI elements (text-based, fast, USE THIS BY DEFAULT for UI inspection)
- take_screenshot: Capture screenshot (high token cost, use only when visual context critical)

**GUIDELINES:**
- Test connectivity before complex operations (e.g., run "adb devices" first)
- Use execute_adb_command for all ADB operations
- Commands execute in /app/codebase directory by default
- Be methodical and verify each step
- Explain your reasoning when planning actions
- If a command fails, analyze the error and try alternative approaches

**EXAMPLE WORKFLOW:**
1. Check emulator connection: execute_adb_command("adb devices")
2. Get device info: get_emulator_info()
3. Run analysis: execute_adb_command("adb shell pm list packages")
4. Verify results and provide summary

Remember: You are working in a containerized environment designed for security testing.
Be systematic, thorough, and explain your thought process.
"""


class SimpleAgent:
    """
    Simple LangGraph-based agent for mobile cybersecurity testing.

    This agent provides a foundation for interacting with Kali Linux and Android emulators.
    It uses LangGraph's ReAct architecture with checkpointing for session persistence.

    Attributes:
        model_name: OpenAI model identifier
        reasoning_effort: Reasoning effort level (low, medium, high, very_high, xhigh)
        enable_reasoning: Whether reasoning mode is enabled
        temperature: Model temperature
        max_iterations: Maximum number of iterations before stopping
        llm: ChatOpenAI language model instance
        graph: Compiled LangGraph workflow
    """

    def __init__(
        self,
        model: str = AgentConfig.MODEL_DEFAULT,
        reasoning_effort: str = AgentConfig.REASONING_EFFORT_DEFAULT,
        enable_reasoning: bool = AgentConfig.REASONING_ENABLED_DEFAULT,
        temperature: float = AgentConfig.TEMPERATURE_DEFAULT,
        max_iterations: int = 100,
    ):
        """
        Initialize the simple agent.

        Args:
            model: OpenAI model to use (default: gpt-5.2)
            reasoning_effort: Reasoning effort level (default: medium)
                             Options: low, medium, high, very_high, xhigh
            enable_reasoning: Whether to enable reasoning mode (default: True)
            temperature: Model temperature (default: 0 for deterministic)
            max_iterations: Maximum iterations before stopping (default: 100)
        """
        self.model_name = model
        self.reasoning_effort = reasoning_effort
        self.enable_reasoning = enable_reasoning
        self.temperature = temperature
        self.max_iterations = max_iterations

        # Get model configuration
        model_config = get_model_config(
            model=model,
            reasoning_effort=reasoning_effort,
            enable_reasoning=enable_reasoning,
            temperature=temperature,
        )

        # Initialize LLM
        self.llm = ChatOpenAI(**model_config)
        self.llm_with_tools = self.llm.bind_tools(KALI_TOOLS)

        agent_logger.info(
            f"Initialized SimpleAgent with model: {model}, "
            f"reasoning: {enable_reasoning}, effort: {reasoning_effort}"
        )

        # Build the graph
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """
        Build the LangGraph workflow.

        The workflow consists of:
        1. Agent node: LLM reasoning and decision making
        2. Tool node: Execute tool calls
        3. Conditional routing between nodes

        Returns:
            Compiled LangGraph workflow with checkpointing
        """
        # Create tool node
        tool_node = ToolNode(KALI_TOOLS)

        # Define agent node
        def agent_node(state: AgentState) -> AgentState:
            """
            Main agent reasoning node.

            This node:
            1. Gets current state (messages, iteration)
            2. Calls LLM with tools
            3. Returns updated state with LLM response
            """
            messages = state["messages"]
            iteration = state.get("iteration", 0)

            agent_logger.info(f"Agent iteration {iteration + 1}/{self.max_iterations}")

            # Check iteration limit
            if iteration >= self.max_iterations:
                agent_logger.warning("Max iterations reached")
                final_message = AIMessage(
                    content=f"Maximum iterations ({self.max_iterations}) reached. "
                    f"Task may be incomplete. Consider increasing max_iterations or "
                    f"breaking down the task into smaller steps."
                )
                return {
                    **state,
                    "messages": [final_message],
                    "iteration": iteration + 1,
                }

            # Call LLM
            try:
                response = self.llm_with_tools.invoke(messages)

                # Log response
                content_preview = (
                    response.content[:300] if response.content else "[No content]"
                )
                agent_logger.info(
                    f"Agent response length: {len(response.content) if response.content else 0} chars"
                )
                agent_logger.debug(f"Agent response preview: {content_preview}...")

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
                error_message = AIMessage(
                    content=f"Error during agent execution: {str(e)}\n\n"
                    f"Please check logs for details."
                )
                return {
                    **state,
                    "messages": [error_message],
                    "iteration": iteration + 1,
                }

        # Define routing logic
        def should_continue(state: AgentState) -> Literal["tools", "end"]:
            """
            Determine if we should continue to tools or end.

            Returns:
                "tools" if there are tool calls to execute
                "end" if we should stop
            """
            messages = state["messages"]
            last_message = messages[-1]

            # Check iteration limit
            if state.get("iteration", 0) >= self.max_iterations:
                agent_logger.info("Routing to END (max iterations)")
                return "end"

            # Check for tool calls
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                agent_logger.info("Routing to TOOLS")
                return "tools"

            # No tool calls, we're done
            agent_logger.info("Routing to END (no tool calls)")
            return "end"

        # Build graph
        workflow = StateGraph(AgentState)

        # Add nodes
        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", tool_node)

        # Set entry point
        workflow.set_entry_point("agent")

        # Add edges
        workflow.add_conditional_edges(
            "agent", should_continue, {"tools": "tools", "end": END}
        )
        workflow.add_edge("tools", "agent")

        # Compile without checkpointing for simplicity and speed
        # Vulnerability analysis typically completes in one run
        # For parallel agent coordination, use SharedKnowledgeStore instead
        compiled_graph = workflow.compile()

        agent_logger.info("LangGraph workflow built successfully")

        return compiled_graph

    def run(self, task: str, config: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Run the agent on a task.

        Args:
            task: Task description for the agent
            config: Optional LangGraph config (e.g., recursion_limit)

        Returns:
            Dictionary with execution results:
                - status: "completed" or "error"
                - iterations: Number of iterations executed
                - final_message: Final agent response
                - messages: Full conversation history

        Example:
            >>> agent = SimpleAgent()
            >>> result = agent.run("Check emulator status")
            >>> print(result['final_message'])
        """
        agent_logger.info("=" * 80)
        agent_logger.info("Starting SimpleAgent Execution")
        agent_logger.info(f"Task: {task}")
        agent_logger.info("=" * 80)

        # Build config
        if config is None:
            config = {}
        
        # Ensure recursion limit is sufficient (max_iterations + buffer)
        # LangGraph defaults to 25, so we must increase it if max_iterations is higher
        if "recursion_limit" not in config:
            config["recursion_limit"] = self.max_iterations + 10

        # Create initial state
        initial_message = HumanMessage(content=task)

        initial_state: AgentState = {
            "messages": [
                SystemMessage(content=SYSTEM_PROMPT),
                initial_message,
            ],
            "iteration": 0,
            "current_task": task,
            "last_command_output": None,
            "executed_commands": [],
            "discovered_info": {},
        }

        # Run the graph
        try:
            final_state = self.graph.invoke(initial_state, config=config)

            # Extract results
            messages = final_state["messages"]
            last_message = messages[-1] if messages else None

            # Get final message content
            final_message = None
            if last_message:
                if isinstance(last_message, AIMessage):
                    final_message = last_message.content
                elif hasattr(last_message, "content"):
                    final_message = last_message.content

            agent_logger.info("=" * 80)
            agent_logger.info("SimpleAgent Execution Completed")
            agent_logger.info(f"Total iterations: {final_state.get('iteration', 0)}")
            agent_logger.info("=" * 80)

            return {
                "status": "completed",
                "iterations": final_state.get("iteration", 0),
                "final_message": final_message,
                "messages": [
                    {
                        "role": getattr(m, "type", "unknown"),
                        "content": getattr(m, "content", str(m)),
                    }
                    for m in messages
                ],
                "state": final_state,
            }

        except Exception as e:
            agent_logger.error(f"Error during agent execution: {e}")
            agent_logger.exception("Full traceback:")

            return {
                "status": "error",
                "error": str(e),
                "iterations": 0,
                "final_message": f"Error: {str(e)}",
            }


# Convenience function for quick testing
def run_simple_agent(
    task: str,
    model: str = "gpt-5.2",
    reasoning_effort: str = "medium",
    enable_reasoning: bool = True,
) -> Dict[str, Any]:
    """
    Convenience function to quickly run the simple agent.

    Args:
        task: Task description
        model: OpenAI model to use
        reasoning_effort: Reasoning effort level
        enable_reasoning: Whether to enable reasoning

    Returns:
        Agent execution results

    Example:
        >>> result = run_simple_agent("Check if emulator is running")
        >>> print(result['final_message'])
    """
    agent = SimpleAgent(
        model=model,
        reasoning_effort=reasoning_effort,
        enable_reasoning=enable_reasoning,
    )
    return agent.run(task=task)
