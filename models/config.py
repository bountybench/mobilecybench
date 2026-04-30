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
    # attacker_model is authoritative in task metadata. At runtime, runner.py
    # reads it from the task bundle and overrides this field. A config-level
    # value is only a dev/debug hint; runtime always defers to metadata.
    # TODO(#979): drop this field — TaskBundle should own attacker_model.
    attacker_model: Optional[Literal["malicious_app", "remote_attacker"]] = None
    # Synthetic-vuln selector (for exploit mode, or for redteam+synthetic).
    # Points at apps/<app>/synthetic_vulnerabilities/<vuln_id>/.
    # No default — configs must declare intent explicitly.
    synthetic_vuln_id: Optional[str] = None
    # Zero-day task selector for redteam mode. Points at
    # zerodays/reports/<app>/<task>/task/ (e.g. task="report-1").
    task: Optional[str] = None
    # When True, the agent receives only the APK (no codebase).
    # When False (default), the agent receives the full source codebase.
    # The two modes are mutually exclusive — we never provide both.
    no_codebase: bool = False

    # When True, RedTeamWorkflow runs only Phase 1 (original APK) and scores
    # solely on whether the app probes triggered after the agent's exploit.
    # No patched-phase comparison, no verifier_diff/patch_diff signals.
    # Intended for APK-only / public-app runs where no fix.patch is available.
    probe_only: bool = False

    # agent limits
    max_iterations: int = Field(gt=0)
    max_model_response_tokens: int = Field(gt=0)

    # agent mode
    agent_mode: Literal["custom", "codex", "claude-code"] = "custom"

    # mode flags
    screenshot_mode: bool
    dry_run: bool
    gold_run: bool = False
    replay_run: Optional[str] = None
    emulator_backend: Literal["native", "container"] = "native"
    emulator_display: Literal["headed", "headless"] = "headed"

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

    # Per-LLM-API-call timeout (milliseconds). Used by the custom agent for
    # provider calls and for docker exec calls into the kali container.
    timeout_ms: int = Field(default=600_000, gt=0)

    # Permit models that are not declared in
    # `agent/model_providers/factory.py:SupportedModel`. Default is False
    # (deny). Intended for model-sweep / exploration runs where the
    # operator is comparing many model variants and is willing to trade
    # accurate cost telemetry for the convenience of not registering each
    # one. When True, an unknown model id falls through to LiteLLMProvider
    # with auto-detected routing and a runtime WARNING.
    # WARNING: cost_usd will report $0 for any run using a model that is
    # not in `utils/token_pricing.json` regardless of this flag — register
    # pricing if cost telemetry matters for the run.
    allow_unregistered_models: bool = False

    # Claude Code CLI timeout (seconds). Only used when agent_mode="claude-code".
    agent_timeout: int = Field(default=1800, gt=0)

    @classmethod
    def from_file(
        cls, config_path: Path, overrides: Optional[dict] = None
    ) -> "RunnerConfig":
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

        if overrides:
            c_dict.update({k: v for k, v in overrides.items() if v is not None})

        return cls(**c_dict)

    @model_validator(mode="after")
    def validate_attacker_model(self) -> "RunnerConfig":
        if self.attacker_model is not None and self.workflow != "redteam":
            raise ValueError(
                f"attacker_model='{self.attacker_model}' requires workflow='redteam'"
            )
        return self

    @model_validator(mode="after")
    def validate_task(self) -> "RunnerConfig":
        """Workflow-specific task selector validation.

        - exploit: requires synthetic_vuln_id.
        - redteam: requires exactly one of task (zeroday) or synthetic_vuln_id
          (synthetic). probe_only=True takes neither and requires attacker_model.
          replay_run bypasses validation.
        """
        if self.replay_run:
            return self
        if self.workflow == "exploit":
            if self.probe_only:
                raise ValueError("probe_only requires workflow='redteam'")
            if not self.synthetic_vuln_id:
                raise ValueError("workflow='exploit' requires synthetic_vuln_id")
            return self
        if self.workflow == "redteam":
            if self.probe_only:
                if self.task or self.synthetic_vuln_id:
                    raise ValueError(
                        "probe_only is mutually exclusive with task / "
                        "synthetic_vuln_id; got "
                        f"task={self.task!r}, "
                        f"synthetic_vuln_id={self.synthetic_vuln_id!r}"
                    )
                if self.gold_run:
                    raise ValueError("probe_only is incompatible with gold_run")
                if not self.attacker_model:
                    raise ValueError(
                        "probe_only requires attacker_model "
                        "('malicious_app' or 'remote_attacker') in runner_config"
                    )
                return self
            if bool(self.task) == bool(self.synthetic_vuln_id):
                raise ValueError(
                    "workflow='redteam' requires exactly one of task "
                    "(zeroday) or synthetic_vuln_id (synthetic); "
                    f"got task={self.task!r}, "
                    f"synthetic_vuln_id={self.synthetic_vuln_id!r}"
                )
        return self

    @model_validator(mode="after")
    def validate_mode_flags(self) -> "RunnerConfig":
        replay_enabled = bool(self.replay_run)
        enabled_modes = [self.dry_run, self.gold_run, replay_enabled]
        if sum(bool(flag) for flag in enabled_modes) > 1:
            raise ValueError("dry_run, gold_run, and replay_run are mutually exclusive")
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
