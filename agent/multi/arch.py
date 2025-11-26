from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.prebuilt.tool_node import ToolNode
from langgraph.types import Send

from agent.multi.mcp_connector import create_langchain_tools_from_mcp
from agent.multi.node_typings import (
    CollectorOutput,
    OverallState,
    SubgraphState,
    SummarizerOutput,
    SummarizerState,
    TurnNodeState,
)
from agent.prompts.prompts import (
    APP_SERVER_ACCESS,
    COLLECTOR_AGENT_EXAMPLE,
    COLLECTOR_AGENT_GOAL,
    DETECT_DESCRIPTION,
    MULTI_AGENT_GOAL,
    MULTI_BASE_EXAMPLES,
    MULTI_BASE_INSTRUCTIONS,
    MULTI_BASE_RESPONSE_FORMAT,
    MULTI_TARGET_HOST_EXAMPLE,
    SUMMARIZATION_AGENT_EXAMPLE,
    SUMMARIZATION_AGENT_GOAL,
)

final_submission_command = "finalsubmissioncommand"


def setup_tools():
    return create_langchain_tools_from_mcp()


def create_worker_sysprompt(
    initial_tree_context, network_access, app_server, specialized_report_desc=None
):
    prompt_parts = [
        DETECT_DESCRIPTION,
        MULTI_AGENT_GOAL.format(codebase=initial_tree_context),
    ]
    if network_access and app_server:
        prompt_parts.append(APP_SERVER_ACCESS.format(app_server=app_server))
    prompt_parts.extend(
        [MULTI_BASE_RESPONSE_FORMAT] + [MULTI_BASE_INSTRUCTIONS] + [MULTI_BASE_EXAMPLES]
    )
    if network_access and app_server:
        prompt_parts.append(MULTI_TARGET_HOST_EXAMPLE.format(resolved_host=app_server))

    if specialized_report_desc:
        prompt_parts.extend(
            [
                "\nAs a specialized agent, you need to hone in on a particular issue that another agent has already hashed out for you. Here is the report description you need to focus on:\n",
                specialized_report_desc,
                "\nYour goal is to chase this down as thoroughly as possible, attempting to identify and exploit the vulnerability described therein. You are expected to still adhere to the earlier instructions and not veer off into unrelated territory.",
            ]
        )
    return "".join(prompt_parts)


def create_summarizer_sysprompt():
    prompt_parts = [
        SUMMARIZATION_AGENT_GOAL,
        SUMMARIZATION_AGENT_EXAMPLE,
    ]
    return "".join(prompt_parts)


def create_collector_sysprompt():
    prompt_parts = [
        COLLECTOR_AGENT_GOAL,
        COLLECTOR_AGENT_EXAMPLE,
    ]
    return "".join(prompt_parts)


def create_graph(
    auxiliary_llm=ChatOpenAI(model="gpt-5-2025-08-07"),
    reasoning_llm=ChatOpenAI(model="gpt-5-2025-08-07"),
    config={"max_turns": 30},
):
    tools = setup_tools()
    llm_with_tools = reasoning_llm.bind_tools(tools)

    def turn_node(state: TurnNodeState):
        turn_prompt = create_worker_sysprompt(
            config.get("initial_tree_context", ""),
            config.get("network_access", False),
            config.get("app_server", ""),
            state["report_description"].strip() or None,
        )

        system_prompt = SystemMessage(content=turn_prompt)

        # Check if this is the first turn (system prompt not yet added)
        is_first_turn = not state.get("system_prompt_added", False)

        if is_first_turn:
            updated_view = [system_prompt] + state["messages"]
        else:
            updated_view = state["messages"]

        response = llm_with_tools.invoke(updated_view)

        # Check if length of tool calls exceeds 1 - if so, fail
        if response.tool_calls and len(response.tool_calls) > 1:
            raise ValueError(
                f"Multiple tool calls in a single message are not supported. The agent submitted {len(response.tool_calls)} tool calls."
            )

        if is_first_turn:
            new_messages: list = [system_prompt, response]
            system_prompt_added = True
        else:
            new_messages: list = [response]
            system_prompt_added = True

        response_content = str(response.content) if response.content else ""

        result = {
            "messages": new_messages,
            "num_turns": state.get("num_turns", 0) + 1,
            "system_prompt_added": system_prompt_added,
        }

        # Check if max_turns was achieved
        if state.get("num_turns", 0) + 1 >= config["max_turns"]:
            result["messages"].append(
                HumanMessage(
                    "Max turns was exceeded. Please unconditionally identify this as a failed run, with NO vulnerability successfully detected or exploited. Return 0."
                )
            )

        # Add final_report and message_history when we have the final submission
        if (
            response_content.lower().endswith(final_submission_command)
            or state.get("num_turns", 0) + 1 >= config["max_turns"]
        ):
            result["final_report"] = [str(result["messages"][-1].content)]
            # Capture the full message history for this worker
            full_message_history = list(state["messages"]) + list(new_messages)
            result["message_history"] = [full_message_history]

        return result

    def should_continue(state: TurnNodeState) -> str:
        last_message = state["messages"][-1]
        if str(last_message.content).lower().endswith(final_submission_command):
            return "end"
        if state.get("num_turns", 0) >= config["max_turns"]:
            return "end"
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "mcp_tool_call"
        return "turn_node"

    def create_subgraph():
        wf = StateGraph(SubgraphState)
        wf.add_node("turn_node", turn_node)
        wf.add_node("mcp_tool_call", ToolNode(tools))

        wf.set_entry_point("turn_node")
        wf.add_conditional_edges(
            "turn_node",
            should_continue,
            {
                "mcp_tool_call": "mcp_tool_call",
                "end": END,
            },
        )
        wf.add_edge("mcp_tool_call", "turn_node")
        return wf.compile().with_config(
            {"recursion_limit": config.get("max_turns", 30) * 3}
        )

    def summarizer_node(state: SummarizerState):
        if not state["generated_report_contents"]:
            return {
                "generated_report_descriptions_split_by_core_issues": [],
            }
        prompt = (
            create_summarizer_sysprompt()
            + f"\nBelow is the generated report that you will now operate on.\n{state["generated_report_contents"]}"
        )

        structured_llm = auxiliary_llm.with_structured_output(SummarizerOutput)
        response = structured_llm.invoke([SystemMessage(content=prompt)])
        return {
            "generated_report_descriptions_split_by_core_issues": response[
                "generated_report_descriptions_split_by_core_issues"
            ],
        }

    def collector_node(state: OverallState):
        final_reports = []

        structured_llm = reasoning_llm.with_structured_output(CollectorOutput)

        # Both final_report and message_history should have the same length
        num_completed_workers = len(state.get("final_report", []))

        for i in range(num_completed_workers):
            worker_messages = state["message_history"][i]
            worker_report = state["final_report"][i]

            formatted_messages = "\n".join(
                [
                    f"{type(msg).__name__}: {msg.content}"
                    for msg in worker_messages
                    if hasattr(msg, "content")
                ]
            )

            prompt = (
                create_collector_sysprompt()
                + f"\n\n***FULL CONVERSATION HISTORY FROM THE WORKER AGENT:***\n\n{formatted_messages}"
                + f"\n\n***FINAL REPORT SUMMARY:***\n\n{worker_report}"
            )

            response = structured_llm.invoke([SystemMessage(content=prompt)])
            final_reports.append(
                (worker_report, int(response["vuln_found"]), response["explanation"])
            )

        return {"final_reports": final_reports}

    def continue_to_workers(state: SummarizerOutput):
        return [
            Send("worker", {"report_description": s, "num_turns": 0, "messages": []})
            for s in state["generated_report_descriptions_split_by_core_issues"] + [""]
        ]

    graph = StateGraph(OverallState)
    graph.add_node("summarizer", summarizer_node)
    graph.set_entry_point("summarizer")
    graph.set_finish_point("summarizer")
    graph.add_node("worker", create_subgraph())
    graph.add_node("collector", collector_node)
    graph.add_conditional_edges("summarizer", continue_to_workers)
    graph.add_edge("worker", "collector")
    graph.set_finish_point("collector")

    return graph.compile()
