from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from agent.multi.arch import create_graph
from agent.agent_helpers import get_directory_tree
from agent.multi.langgraph_pricing_tracker import LangGraphPricingTracker

# Load environment variables from .env file
load_dotenv()


def obtain_vuln_file_contents(filepaths):
    file_contents = []
    for filepath in filepaths:
        with open(filepath, "r") as f:
            content = f.read()
        file_contents.append(content)
    return "\n".join(file_contents)


def call_pipeline(
    list_of_vuln_files=[],
    auxiliary_llm=ChatOpenAI(model="gpt-5-2025-08-07"),
    reasoning_llm=ChatOpenAI(model="gpt-5-2025-08-07"),
    config={
        "max_turns": 30,
        "initial_tree_context": "",
        "app_server": "",
        "network_access": False,
    },
    track_pricing=True,
    pricing_output_file="langgraph_pricing.json",
):
    """Run the multi-agent vulnerability detection pipeline.

    Args:
        list_of_vuln_files: List of vulnerability report files to analyze
        auxiliary_llm: LLM for summarizer/collector nodes
        reasoning_llm: LLM for worker agent nodes
        config: Pipeline configuration dictionary
        track_pricing: If True, tracks and saves token usage/pricing data
        pricing_output_file: Path to save pricing JSON file (if track_pricing=True)

    Returns:
        Dictionary with pipeline results and pricing information (if tracked)
    """
    # Initialize pricing tracker if requested
    tracker = None
    if track_pricing:
        tracker = LangGraphPricingTracker()
        # Wrap LLMs with pricing callbacks
        auxiliary_llm = tracker.wrap_llm(auxiliary_llm, role="auxiliary")
        reasoning_llm = tracker.wrap_llm(reasoning_llm, role="reasoning")

    # Create and run the multi-agent graph
    multi_agent_system_graph = create_graph(
        auxiliary_llm=auxiliary_llm, reasoning_llm=reasoning_llm, config=config
    )

    result = multi_agent_system_graph.invoke(
        {
            "generated_report_contents": obtain_vuln_file_contents(
                filepaths=list_of_vuln_files
            ),
            "generated_report_descriptions_split_by_core_issues": [],
            "final_reports": [],
            "final_report": [],
            "message_history": [],
        }
    )

    # Save pricing data if tracking was enabled
    if tracker:
        tracker.log_summary()
        tracker.save_to_file(pricing_output_file)
        summary = tracker.get_summary()
        result["pricing"] = {
            "total_cost_usd": summary.total_cost_usd,
            "total_calls": summary.total_calls,
            "total_input_tokens": summary.total_input_tokens,
            "total_output_tokens": summary.total_output_tokens,
            "output_file": pricing_output_file,
        }

    return result
