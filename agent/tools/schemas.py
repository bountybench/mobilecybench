from typing import List

from pydantic import BaseModel, Field


class ExecuteCommand(BaseModel):
    command: str = Field(..., description="The command to execute in the terminal.")


class GetUIState(BaseModel):
    pass


class ExecuteCommandWithUI(BaseModel):
    command: str = Field(..., description="The command to execute in the terminal.")


class PlanStep(BaseModel):
    step: str = Field(..., description="Description of this step.")
    status: str = Field(..., description="One of: pending, in_progress, completed")

# From gpt-5/codex_prompting_guide - https://cookbook.openai.com/examples/gpt-5/codex_prompting_guide
class UpdatePlan(BaseModel):
    """Updates the task plan. Provide an optional explanation and a list of plan items, each with a step and status. At most one step can be in_progress at a time."""

    explanation: str = Field("", description="Optional context for plan update.")
    plan: List[PlanStep] = Field(..., description="The list of steps.")
