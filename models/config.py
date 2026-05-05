"""Runner configuration model.

Single source of truth for `runner_config.json`. Each field carries a
``description`` that surfaces in three places:

  1. ``schemas/runner_config.schema.json`` — generated from
     ``RunnerConfig.model_json_schema()`` and committed for editor / IDE
     autocomplete and hover-docs (VSCode, JetBrains, Neovim).
  2. ``python runner.py --explain-config`` — terminal users get the same
     schema without leaving the CLI.
  3. ``documentation/EXPERIMENTS.md`` — prose for cross-field semantics
     (workflow/task XOR, mode-flag mutual exclusion) and pointers to the
     two surfaces above.

A CI parity test (``tests/test_runner_config_schema.py``) fails the
build if the committed JSON Schema drifts from this model.
"""

import json
from pathlib import Path
from typing import ClassVar, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from agent.tools import ToolName


class RunnerConfig(BaseModel):
    """Configuration for a single ``runner.py`` invocation.

    Cross-field invariants enforced by validators:

    * ``attacker_model`` is meaningful only when ``workflow == 'redteam'``.
    * ``exploit`` requires ``synthetic_vuln_id``.
    * ``redteam`` (two-phase) requires exactly one of ``task`` (zero-day)
      or ``synthetic_vuln_id`` (synthetic).
    * ``probe_only`` requires ``workflow == 'redteam'``, forbids ``task``
      and ``synthetic_vuln_id``, requires ``attacker_model``, and is
      incompatible with ``gold_run``.
    * ``dry_run``, ``gold_run``, and ``replay_run`` are mutually exclusive.

    See ``documentation/EXPERIMENTS.md`` for the prose walkthrough.
    """

    # ---- App, build & access ------------------------------------------------
    build_type: Literal["source", "download-apk", "skip-apk"] = Field(
        ...,
        description=(
            "How to acquire the APK: build from source, download a published "
            "artifact, or assume it is already in apps/<app>/apk/."
        ),
    )
    no_codebase: bool = Field(
        default=False,
        description=(
            "When true, the agent receives only the APK at /app/apk/. When "
            "false (default), full source is mounted at /app/codebase."
        ),
    )

    # ---- Model & agent ------------------------------------------------------
    model: str = Field(
        ...,
        min_length=1,
        description=(
            "Model id for the custom agent (e.g. gpt-5.5, claude-opus-4-7, "
            "gemini-3.1-pro). Forwarded to codex mode. Ignored by "
            "claude-code. See agent/model_providers/factory.py:SupportedModel."
        ),
    )
    agent_image: str = Field(
        ...,
        min_length=1,
        description=(
            "Docker image used to run the agent (e.g. "
            "cybench/mobilecybench:latest). Pulled implicitly on first use."
        ),
    )
    agent_mode: Literal["custom", "codex", "claude-code"] = Field(
        default="custom",
        description=(
            "Agent implementation: 'custom' (built-in per-turn loop, "
            "default), 'codex' (OpenAI Codex CLI), or 'claude-code' "
            "(Claude Code CLI)."
        ),
    )
    max_iterations: int = Field(
        ...,
        gt=0,
        description="Maximum agent turns before stopping. Custom agent only.",
    )
    max_model_response_tokens: int = Field(
        ...,
        gt=0,
        description="Per-call output token cap forwarded to the provider.",
    )
    custom_system_prompt: Optional[str] = Field(
        default=None,
        description=(
            "Free-form text appended to the workflow-built system prompt "
            "(after any per-app additional_info from metadata.json). Applies "
            "to all agent modes."
        ),
    )
    allowed_tools: Optional[List[ToolName]] = Field(
        default=None,
        description=(
            "Restrict the tool surface. Each entry must be one of "
            "agent.tools.TOOL_NAMES. Null = all tools. Custom agent only — "
            "codex and claude-code use their CLI's native tool surface and "
            "ignore this field."
        ),
    )
    reasoning_effort: Optional[str] = Field(
        default=None,
        description=(
            "Reasoning effort hint (e.g. 'low', 'medium', 'high'). Forwarded "
            "to the provider by the custom agent and to the Codex CLI by "
            "codex mode. Ignored by claude-code."
        ),
    )
    allow_unregistered_models: bool = Field(
        default=False,
        description=(
            "Permit models that are not declared in "
            "agent/model_providers/factory.py:SupportedModel. When true, "
            "falls through to LiteLLM with auto-detected routing and a "
            "runtime WARNING. cost_usd reports $0 for any model that lacks "
            "a row in utils/token_pricing.json regardless of this flag."
        ),
    )

    # ---- Workflow & task selectors -----------------------------------------
    workflow: Literal["exploit", "redteam"] = Field(
        default="exploit",
        description=(
            "Pipeline to run. 'exploit' requires synthetic_vuln_id; "
            "'redteam' requires exactly one of task (zero-day) or "
            "synthetic_vuln_id (synthetic)."
        ),
    )
    attacker_model: Optional[Literal["malicious_app", "remote_attacker"]] = Field(
        default=None,
        description=(
            "Two-phase redteam: dev/debug hint only — runtime reads the "
            "authoritative value from the task bundle's metadata.json and "
            "logs any override. probe_only: required and authoritative — "
            "there is no task metadata.json to read from. See "
            "documentation/REDTEAM.md."
        ),
    )
    synthetic_vuln_id: Optional[str] = Field(
        default=None,
        description=(
            "Names a directory under apps/<app>/synthetic_vulnerabilities/. "
            "Required for workflow='exploit'; one of {this, task} required "
            "for workflow='redteam'."
        ),
    )
    task: Optional[str] = Field(
        default=None,
        description=(
            "Zero-day task selector for workflow='redteam'. Names a "
            "directory under zerodays/reports/<app>/."
        ),
    )
    probe_only: bool = Field(
        default=False,
        description=(
            "redteam-only bundle-less mode: single replay against the "
            "app's baseline APK, no patch / no verifier / no two-phase "
            "comparison. Score is signal/no_signal based on app probes. "
            "Forbids task and synthetic_vuln_id; requires attacker_model. "
            "Incompatible with gold_run. See "
            "documentation/REDTEAM.md#probe-only-mode."
        ),
    )

    # ---- Mode flags (mutually exclusive) ------------------------------------
    dry_run: bool = Field(
        ...,
        description=(
            "If true, launches an interactive Kali shell instead of the "
            "agent. Useful for verifying setup without API credits."
        ),
    )
    gold_run: bool = Field(
        default=False,
        description=(
            "Replay the task's reference exploit through the full pipeline "
            "instead of invoking the agent. Mutually exclusive with dry_run."
        ),
    )
    replay_run: Optional[str] = Field(
        default=None,
        description=(
            "Replay a prior redteam exploit artifact from "
            "logs/experiment_<uuid>. May also be set via runner.py "
            "--replay-run. Mutually exclusive with dry_run and gold_run."
        ),
    )
    screenshot_mode: bool = Field(
        ...,
        description=(
            "Capture a per-turn PNG screenshot under logs/experiment_<uuid>"
            "/screenshots/. Adds ~10s per turn plus disk usage."
        ),
    )

    # ---- Emulator -----------------------------------------------------------
    emulator_backend: Literal["native", "container"] = Field(
        default="native",
        description=(
            "Run the emulator as a host process ('native') or as a separate "
            "Docker container ('container', used by GKE)."
        ),
    )
    emulator_display: Literal["headed", "headless"] = Field(
        default="headed",
        description="Whether the emulator opens a window.",
    )
    emulator_boot_timeout_seconds: int = Field(
        default=300,
        gt=0,
        description="How long to wait for the emulator to be ready (seconds).",
    )

    # ---- Timeouts -----------------------------------------------------------
    script_timeout: int = Field(
        default=600,
        gt=0,
        description=(
            "Seconds for long-running scripts (exploit, verify, setup, " "prepare_app)."
        ),
    )
    build_command_timeout: int = Field(
        default=1200,
        gt=0,
        description="Seconds for the APK build command.",
    )
    apk_timeout: int = Field(
        default=60,
        gt=0,
        description=(
            "am instrument timeout (seconds) for the malicious-APK replay " "path."
        ),
    )
    timeout_ms: int = Field(
        default=600_000,
        gt=0,
        description=(
            "Per-LLM-API-call timeout (milliseconds). Used by the custom "
            "agent for provider calls and for docker exec calls into the "
            "kali container."
        ),
    )
    agent_timeout: int = Field(
        default=1800,
        gt=0,
        description=(
            "Seconds for CLI-based agents (codex, claude-code). Custom "
            "agent uses timeout_ms instead."
        ),
    )

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

        # `$schema` (and any future tooling-only keys) are ignored by
        # pydantic's default extra='ignore', but strip them explicitly so
        # config-export round trips stay clean.
        c_dict.pop("$schema", None)

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

    # ------------------------------------------------------------------
    # Schema export
    # ------------------------------------------------------------------
    #
    # The committed schemas/runner_config.schema.json document is the
    # contract editors / external tooling read for autocomplete +
    # hover-docs and sweep-config validation. Build it here so the model
    # is the single source of truth; the generator script and the CI
    # parity test both call ``render_json_schema``.

    JSON_SCHEMA_DRAFT: ClassVar[str] = "https://json-schema.org/draft/2020-12/schema"
    JSON_SCHEMA_ID: ClassVar[str] = (
        "https://mobilecybench.dev/schemas/runner_config.schema.json"
    )
    JSON_SCHEMA_TITLE: ClassVar[str] = "Runner Config"

    @classmethod
    def build_json_schema(cls) -> dict:
        """Return the canonical JSON Schema dict for ``RunnerConfig``.

        Pydantic emits the per-field schema (types, defaults, enums,
        descriptions); we wrap it with the same draft / $id / title
        metadata used by the other ``schemas/*.json`` documents so the
        directory stays internally consistent.
        """
        body = cls.model_json_schema()
        return {
            "$schema": cls.JSON_SCHEMA_DRAFT,
            "$id": cls.JSON_SCHEMA_ID,
            "title": cls.JSON_SCHEMA_TITLE,
            **{k: v for k, v in body.items() if k != "title"},
        }

    @classmethod
    def render_json_schema(cls) -> str:
        """Serialize :meth:`build_json_schema` with stable, diffable formatting."""
        return json.dumps(cls.build_json_schema(), indent=2, ensure_ascii=False) + "\n"
