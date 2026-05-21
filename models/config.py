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
from typing import Any, ClassVar, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    * ``dry_run`` and ``gold_run`` are mutually exclusive.

    See ``documentation/EXPERIMENTS.md`` for the prose walkthrough.
    """

    model_config = ConfigDict(extra="forbid")

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
            "Model id (e.g. gpt-5.5, claude-opus-4-7, gemini-3.1-pro-preview). "
            "Custom path: routed via agent/custom/model_providers/factory.py. "
            "External path: forwarded to the in-container CLI."
        ),
    )
    agent_image: str = Field(
        ...,
        min_length=1,
        description=(
            "Docker image the agent runs from. Custom path: kali base "
            "(e.g. cybench/mobilecybench:latest). External path: BYO "
            "reference image (e.g. cybench/mobilecybench:codex_0.130.0-r2, "
            ":claudecode_2.1.140-r2, or a lab's own tag)."
        ),
    )
    agent_mode: Literal["custom", "external"] = Field(
        default="custom",
        description=(
            "Dispatch path. 'custom' (default): in-process Python loop. "
            "'external': BYO Docker image satisfying the contract in "
            "documentation/BRING_YOUR_OWN_AGENT.md (covers codex, "
            "claude-code, and lab-supplied agents)."
        ),
    )
    max_iterations: int = Field(
        ...,
        gt=0,
        description="Maximum agent turns before stopping. Custom path only.",
    )
    max_model_response_tokens: int = Field(
        ...,
        gt=0,
        description="Per-call output token cap forwarded to the provider.",
    )
    additional_system_prompt: Optional[str] = Field(
        default=None,
        description=(
            "Free-form text appended to the workflow-built system prompt "
            "(after any per-app additional_info from metadata.json). Applies "
            "to all agent modes."
        ),
    )
    reasoning_effort: Optional[Literal["low", "medium", "high"]] = Field(
        default=None,
        description=(
            "Reasoning effort hint forwarded to providers that accept it. "
            "Models without a reasoning-effort knob ignore this field."
        ),
    )
    allow_unregistered_models_in_custom_mode: bool = Field(
        default=False,
        title="Allow Unregistered Models in Custom Mode",
        description=(
            "Permit models that are not declared in "
            "agent/custom/model_providers/factory.py:SupportedModel when "
            "agent_mode='custom'. Custom mode then falls through to LiteLLM "
            "with auto-detected routing and a runtime WARNING. External "
            "mode is BYO-owned and does not use this custom-mode registry; "
            "the external image owns model validation. Models without a row "
            "in utils/token_pricing.json "
            "report cost_source='derived_unpriced' unless the agent reports "
            "cost."
        ),
    )

    # ---- Workflow & task selectors -----------------------------------------
    workflow: Literal["exploit", "redteam"] = Field(
        default="exploit",
        description=(
            "Pipeline to run. 'exploit' requires synthetic_vuln_id; "
            "two-phase 'redteam' requires exactly one of task (zero-day) "
            "or synthetic_vuln_id (synthetic); 'redteam' with "
            "probe_only=true forbids both."
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
            "for two-phase redteam; forbidden when probe_only=true."
        ),
    )
    task: Optional[str] = Field(
        default=None,
        description=(
            "Zero-day task selector for two-phase redteam. Names a "
            "directory under zerodays/reports/<app>/. Forbidden when "
            "probe_only=true."
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

    # ---- Network --------------------------------------------------------------
    network_mode: Literal["restricted", "permissive"] = Field(
        default="permissive",
        description=(
            "Squid egress policy. 'permissive' (default): any public host. "
            "'restricted': exact-FQDN allowlist (LLM APIs + apt/pip mirrors). "
            "Kernel routing (agent_net internal:true) applies in both."
        ),
    )

    # ---- Timeouts -----------------------------------------------------------
    script_timeout: int = Field(
        default=600,
        gt=0,
        description="Seconds for long-running scripts (exploit, verify, setup, prepare_app).",
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
            "HARD wall-clock deadline (seconds) for the malicious-APK replay "
            "to write done.marker; agent cannot extend by withholding it."
        ),
    )
    llm_request_timeout_ms: int = Field(
        default=600_000,
        gt=0,
        description=(
            "Per-LLM-API-call timeout (milliseconds). Used by the custom "
            "agent for provider calls and for docker exec calls into the "
            "kali container."
        ),
    )
    agent_wallclock_seconds: int = Field(
        default=1800,
        gt=0,
        description=(
            "Harness-side wall-clock kill budget for external agents "
            "(SIGKILL on expiry). Custom agent ignores this and is bounded "
            "by max_iterations + llm_request_timeout_ms."
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

        # Strip tooling-only keys before validation; the model is strict
        # (``extra='forbid'``) and would reject them otherwise.
        c_dict.pop("$schema", None)

        if overrides:
            c_dict.update({k: v for k, v in overrides.items() if v is not None})

        return cls(**c_dict)

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_agent_modes(cls, data: Any) -> Any:
        """Reject pre-BYO ``agent_mode: "codex"|"claude-code"`` with migration hint."""
        if not isinstance(data, dict):
            return data
        mode = data.get("agent_mode")
        if mode in ("codex", "claude-code"):
            raise ValueError(
                f"agent_mode={mode!r} is no longer supported. "
                f'Migrate to: agent_mode="external" with the {mode} reference image. '
                f"See documentation/BRING_YOUR_OWN_AGENT.md for the current tag."
            )
        return data

    @model_validator(mode="after")
    def validate_probe_only_workflow(self) -> "RunnerConfig":
        """probe_only is a redteam-only mode. Declared before
        ``validate_attacker_model`` so on ``workflow=exploit + probe_only=True``
        the operator sees the probe_only mismatch, not the secondary
        attacker_model symptom (validators run in declaration order).
        """
        if self.probe_only and self.workflow != "redteam":
            raise ValueError(
                f"probe_only=True requires workflow='redteam'; "
                f"got workflow={self.workflow!r}"
            )
        return self

    @model_validator(mode="after")
    def validate_attacker_model(self) -> "RunnerConfig":
        if self.attacker_model is not None and self.workflow != "redteam":
            raise ValueError(
                f"attacker_model='{self.attacker_model}' requires workflow='redteam'"
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
        """
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
        """dry_run and gold_run are mutually exclusive runner branches.

        probe_only + dry_run is also rejected: dry_run short-circuits to the
        interactive shell before scoring. (probe_only + gold_run is handled
        by validate_gold_run_probe_only.)
        """
        if self.dry_run and self.gold_run:
            raise ValueError("dry_run and gold_run are mutually exclusive")
        if self.probe_only and self.dry_run:
            raise ValueError(
                "probe_only is incompatible with dry_run: dry_run drops into "
                "an interactive shell and skips scoring entirely."
            )
        return self

    # ---- Schema export (single source of truth for runner_config.schema.json) ----

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
