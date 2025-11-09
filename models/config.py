import json
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class RunnerConfig(BaseModel):
    build_type: Literal["source", "download-apk", "skip-apk"]
    model: str = Field(min_length=1)
    agent_image: str = Field(min_length=1)

    # access control
    server_access: bool
    adb_access: Literal["none", "limited", "full"]

    # agent limits
    max_iterations: int = Field(gt=0)
    max_kali_message_tokens: int = Field(gt=0)
    max_model_response_tokens: int = Field(gt=0)
    max_context_length: int = Field(gt=0)

    # mode flags
    screenshot_mode: bool
    headless_mode: bool
    dry_run: bool
    docker_mode: bool
    wait_for_quit: bool

    # optional
    custom_system_prompt: Optional[str] = None
    allowed_tools: Optional[List[str]] = None
    codex_agent_image: Optional[str] = "cybench/mobilecybench:codex"

    @classmethod
    def from_file(cls, config_path: Path) -> "RunnerConfig":
        if not config_path.exists():
            raise FileNotFoundError(
                f"Runner configuration file not found: {config_path}"
            )
        try:
            with open(config_path, "r") as f:
                c_dict = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in config file: {e}")
        except Exception as e:
            raise ValueError(f"Unexpected error reading config file: {e}")

        return cls(**c_dict)

    @field_validator("allowed_tools", mode="after")
    @classmethod
    def validate_allowed_tools(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        # TODO: should consider a single truth of source MCP tools registry or constants file
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
