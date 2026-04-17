import json
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class RunnerConfig(BaseModel):
    # TODO - Look into internal docker network - something we can use to limit codex agent permissions
    # TODO - separate out runner configuration based on what agent mode
    build_type: Literal["source", "download-apk", "skip-apk"]
    model: str = Field(min_length=1)
    agent_image: str = Field(min_length=1)

    # access control
    server_access: bool
    adb_access: Literal["none", "limited", "full"]

    # workflow type
    workflow: Literal["exploit", "redteam"] = "exploit"
    attack_model: Literal["malicious_apk", "auth_attacker"] = "malicious_apk"
    synthetic_vuln_id: str = "vuln_0"  # which vulnerability to test in exploit mode
    # When True, the agent receives only the APK (no codebase).
    # When False (default), the agent receives the full source codebase.
    # The two modes are mutually exclusive — we never provide both.
    no_codebase: bool = False

    # agent limits
    max_iterations: int = Field(gt=0)
    max_model_response_tokens: int = Field(gt=0)

    # agent mode
    agent_mode: Literal["custom", "codex", "claude-code"] = "custom"

    # mode flags
    screenshot_mode: bool
    dry_run: bool
    gold_run: bool = False
    emulator_backend: Literal["native", "container"] = "native"
    emulator_display: Literal["headed", "headless"] = "headed"

    # zero-day report (uses exploit from zerodays submodule)
    gold_report: Optional[str] = None

    # optional
    custom_system_prompt: Optional[str] = None
    allowed_tools: Optional[List[str]] = None

    reasoning_effort: Optional[str] = None

    # General timeout (seconds) for long-running scripts (setup, exploit, verify, etc.)
    script_timeout: int = Field(default=600, gt=0)
    build_command_timeout: int = Field(default=1200, gt=0)
    apk_timeout: int = Field(
        default=60, gt=0
    )  # am instrument timeout for malicious APK replay
    emulator_boot_timeout_seconds: int = Field(default=300, gt=0)

    # Claude Code CLI timeout (seconds). Only used when agent_mode="claude-code".
    agent_timeout: int = Field(default=1800, gt=0)

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

    @model_validator(mode="after")
    def validate_attack_model(self) -> "RunnerConfig":
        if self.attack_model != "malicious_apk" and self.workflow != "redteam":
            raise ValueError(
                f"attack_model='{self.attack_model}' requires workflow='redteam'"
            )
        return self

    @model_validator(mode="after")
    def validate_gold_run(self) -> "RunnerConfig":
        if self.gold_report:
            self.gold_run = True
        if self.gold_run and self.workflow not in ("exploit", "redteam"):
            raise ValueError(
                "gold_run=True is only valid with workflow='exploit' or 'redteam'"
            )
        if self.gold_run and self.dry_run:
            raise ValueError(
                "gold_run and dry_run cannot both be True — "
                "gold_run executes exploit files and requires real evaluation"
            )
        return self

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
