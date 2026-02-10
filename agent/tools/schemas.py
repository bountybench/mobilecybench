from pydantic import BaseModel, Field


class ExecuteCommand(BaseModel):
    command: str = Field(..., description="The command to execute in the terminal.")


class GetUIState(BaseModel):
    pass


class ExecuteCommandWithUI(BaseModel):
    command: str = Field(..., description="The command to execute in the terminal.")
