import operator
from typing import Annotated, TypedDict

from langgraph.graph import MessagesState


class TurnNodeState(MessagesState):
    report_description: str
    num_turns: int
    system_prompt_added: bool
    final_report: Annotated[list[str], operator.add]


class SubgraphState(MessagesState):
    report_description: str
    num_turns: int
    system_prompt_added: bool
    final_report: Annotated[list[str], operator.add]
    message_history: Annotated[list[list], operator.add]


class OverallState(TypedDict):
    generated_report_contents: str
    generated_report_descriptions_split_by_core_issues: list[str]
    final_reports: Annotated[list[tuple[str, int, str]], operator.add]
    final_report: Annotated[list[str], operator.add]
    message_history: Annotated[list[list], operator.add]


class SummarizerState(TypedDict):
    generated_report_contents: str


class SummarizerOutput(TypedDict):
    generated_report_descriptions_split_by_core_issues: list[str]


class CollectorOutput(TypedDict):
    vuln_found: bool
    explanation: str
