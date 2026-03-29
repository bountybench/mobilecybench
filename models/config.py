import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class RunnerConfig(BaseModel):
    # ── Environment ────────────────────────────────────────────────
    build_type: Literal["source", "download-apk", "skip-apk"]
    agent_image: str = Field(min_length=1)
    emulator_backend: Literal["native", "container"]
    emulator_display: Literal["headed", "headless"]
    emulator_boot_timeout_seconds: int = Field(gt=0)
    build_command_timeout: int = Field(gt=0)
    script_timeout: int = Field(gt=0)

    # ── Workflow ───────────────────────────────────────────────────
    workflow: Literal["discovery", "exploit", "detection", "unified"]
    synthetic_vuln_id: str  # which vulnerability to test (exploit only)
    dry_run: bool
    gold_run: bool

    # ── Agent ──────────────────────────────────────────────────────
    agent_mode: Literal["custom", "codex", "claude-code"]
    # custom agent only:
    model: str = Field(min_length=1)
    max_iterations: int = Field(gt=0)
    max_model_response_tokens: int = Field(gt=0)
    screenshot_mode: bool
    reasoning_effort: Optional[str]
    # claude-code agent only:
    agent_timeout: int = Field(gt=0)

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
    def validate_gold_run(self) -> "RunnerConfig":
        if self.gold_run and self.workflow not in ("exploit", "unified"):
            raise ValueError(
                "gold_run=True is only valid with workflow='exploit' or 'unified'"
            )
        if self.gold_run and self.dry_run:
            raise ValueError(
                "gold_run and dry_run cannot both be True — "
                "gold_run executes exploit files and requires real evaluation"
            )
        return self
