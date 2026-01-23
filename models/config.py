import json
from pathlib import Path
from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


class EnvironmentConfig(BaseModel):
    build_type: Literal["source", "download-apk", "skip-apk"]
    server_access: bool
    adb_access: Literal["none", "limited", "full"]
<<<<<<< HEAD
=======
    synthetic_vuln: bool = False

    # agent limits
    max_iterations: int = Field(gt=0)
    max_kali_message_tokens: int = Field(gt=0)
    max_model_response_tokens: int = Field(gt=0)
    max_context_length: int = Field(gt=0)

    # mode flags
>>>>>>> b42b2510e3ff633db631771eee2d175955f50117
    screenshot_mode: bool
    headless_mode: bool
    dry_run: bool
    docker_mode: bool


class CustomAgentConfig(BaseModel):
    model: str = Field(min_length=1)
    agent_image: str = "cybench/mobilecybench:latest"
    max_iterations: int = Field(gt=0, default=30)
    max_kali_message_tokens: int = Field(gt=0, default=8192)
    max_model_response_tokens: int = Field(gt=0, default=8192)
    max_context_length: int = Field(gt=0, default=200000)
    reasoning_effort: Optional[str] = "medium"
    custom_system_prompt: Optional[str] = None
    allowed_tools: Optional[List[str]] = None

    @field_validator("allowed_tools", mode="after")
    @classmethod
    def validate_allowed_tools(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        # TODO: should consider a single truth of source tools registry or constants file
        # currently hardcode as we don't have that file yet
        valid_tools = {
            "execute_command",
            "get_current_ui_state",
            "execute_command_with_ui_state",
        }
        invalid = set(value) - valid_tools
        if invalid:
            raise ValueError(
                f"Invalid tools found in allowed_tools: {invalid}\n"
                f"Supported tools are: {valid_tools}"
            )
        return value


class SupervisorAgentConfig(BaseModel):
    # Example fields for supervisor
    hierarchy_model: str = Field(min_length=1)
    worker_model: str
    max_iterations: int = 10
    allowed_tools: Optional[List[str]] = None

    @field_validator("allowed_tools", mode="after")
    @classmethod
    def validate_allowed_tools(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        # TODO: should consider a single truth of source tools registry or constants file
        # currently hardcode as we don't have that file yet
        valid_tools = {
            "execute_command",
            "get_current_ui_state",
            "execute_command_with_ui_state",
        }
        invalid = set(value) - valid_tools
        if invalid:
            raise ValueError(
                f"Invalid tools found in allowed_tools: {invalid}\n"
                f"Supported tools are: {valid_tools}"
            )
        return value


class RunnerConfig(BaseModel):
    # TODO - Look into internal docker network - something we can use to limit codex agent permissions
    # TODO - separate out runner configuration based on what agent mode
    environment: EnvironmentConfig
    agents: Dict[str, Union[CustomAgentConfig, SupervisorAgentConfig]]
    # Or strict typing:
    # custom_agent: Optional[CustomAgentConfig]
    # supervisor_agent: Optional[SupervisorAgentConfig]

    @classmethod
    def from_file(cls, config_path: Path) -> "RunnerConfig":
        if not config_path.exists():
            raise FileNotFoundError(
                f"Runner configuration file not found: {config_path}"
            )
        try:
            with open(config_path, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in config file: {e}")
        except Exception as e:
            raise ValueError(f"Unexpected error reading config file: {e}")

        return cls(**data)
