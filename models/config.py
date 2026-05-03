import json
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from agent.tools import ToolName


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
    # Authoritative source depends on mode:
    #   - Two-phase redteam (synthetic / zeroday): bundle reads it from
    #     <task_dir>/metadata.json::attacker_model. Workflow init syncs the
    #     effective value back into config so prompts/credentials see one
    #     consistent value (logs the override when config differed).
    #   - Probe-only (variants 4 / 5, bundle-less): config is authoritative
    #     because there is no task metadata.json to read from.
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
    allowed_tools: Optional[List[ToolName]] = None

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
        config_path = Path(config_path)
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
    def validate_probe_only_workflow(self) -> "RunnerConfig":
        """probe_only is a redteam-only mode. On other workflows it would
        be silently ignored, which violates the truthful-config contract
        (operator reads probe_only=True and assumes it took effect)."""
        if self.probe_only and self.workflow != "redteam":
            raise ValueError(
                f"probe_only=True requires workflow='redteam'; "
                f"got workflow={self.workflow!r}"
            )
        return self

    @model_validator(mode="after")
    def validate_gold_run_probe_only(self) -> "RunnerConfig":
        """gold_run resolves a canonical exploit source; probe_only has
        none (no patch / no verifier / no replayable artifact). Reject
        early instead of failing at gold-source resolution."""
        if self.gold_run and self.probe_only:
            raise ValueError(
                "gold_run is incompatible with probe_only: probe_only has "
                "no canonical exploit source to resolve. Run interactively "
                "with the same probe_only config instead."
            )
        return self

    @model_validator(mode="after")
    def validate_task(self) -> "RunnerConfig":
        """Workflow-specific task selector validation.

        - exploit: requires synthetic_vuln_id.
        - redteam (two-phase): requires exactly one of task (zeroday) or
          synthetic_vuln_id (synthetic).
        - redteam + probe_only: bundle-less mode is allowed when neither
          task nor synthetic_vuln_id is set, but attacker_model must be
          set on the config (no task metadata.json to read it from).
          replay_run bypasses validation.
        """
        if self.replay_run:
            return self
        if self.workflow == "exploit":
            if not self.synthetic_vuln_id:
                raise ValueError("workflow='exploit' requires synthetic_vuln_id")
            return self
        if self.workflow == "redteam":
            has_task = bool(self.task)
            has_vuln = bool(self.synthetic_vuln_id)
            if self.probe_only:
                # Probe-only is bundle-less by design: the bundle's
                # patch/verifier are irrelevant, and accepting a task or
                # vuln_id alongside probe_only invites operator confusion
                # ("did vuln_0 get applied?" — no).
                if has_task or has_vuln:
                    raise ValueError(
                        "probe_only is bundle-less: do not set task or "
                        "synthetic_vuln_id; got "
                        f"task={self.task!r}, "
                        f"synthetic_vuln_id={self.synthetic_vuln_id!r}"
                    )
                if not self.attacker_model:
                    raise ValueError(
                        "probe_only requires attacker_model to be set on "
                        "the config (no bundle metadata to read it from)"
                    )
                return self
            # Two-phase redteam: bundle is mandatory.
            if has_task == has_vuln:
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
