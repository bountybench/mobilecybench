import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field


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

    # optional
    custom_system_prompt: Optional[str] = None

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
            raise ValueError(f"Invalid JSON in config file {e}")
        except Exception as e:
            raise ValueError(f"Unexpected Error in reading config file {e}")

        return cls(**c_dict)
