"""Runner configuration input model.

Single source of truth for ``runner_config.json``. The nested shape encodes
cross-section invariants in the type system: discriminated ``workflow`` and
``agent`` blocks make invalid combinations unrepresentable (e.g. probe-only
cannot carry ``task``; external mode cannot carry ``max_iterations``).

Each field's ``description`` surfaces in three places:

  1. ``schemas/runner_config.schema.json`` — generated from
     ``RunnerConfig.model_json_schema()`` and committed for IDE autocomplete.
  2. ``python runner.py --explain-config`` — CLI dump of the schema.
  3. ``documentation/EXPERIMENTS.md`` — prose walkthrough.

A CI parity test (``tests/test_runner_config_schema.py``) fails the build if
the committed schema drifts from this model.
"""

import json
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.custom.model_providers.factory import MODEL_REGISTRY
from agent.custom.model_providers.litellm_provider import lookup_rule

# Image-tag prefix (the part before "_<version>" in the Docker tag) → set of
# ProviderRule.provider tags ("anthropic", "openai", ...) that the CLI in that
# image can call. Reference images follow the `<prefix>_<version>-r<rev>` tag
# convention documented in BRING_YOUR_OWN_AGENT.md. Unknown prefixes skip the
# compat check; lab/BYO images are unconstrained.
AttackerModel = Literal["malicious_app", "remote_attacker"]


_CLI_IMAGE_COMPAT: dict[str, set[str]] = {
    "claudecode": {"anthropic"},
    "codex": {"openai"},
}


def _cli_family(agent_image: str) -> Optional[str]:
    """Return the CLI prefix for a known reference image, else None."""
    tag = agent_image.rsplit(":", 1)[-1] if ":" in agent_image else agent_image
    for prefix in _CLI_IMAGE_COMPAT:
        if tag.startswith(prefix + "_"):
            return prefix
    return None


class _Strict(BaseModel):
    """Base for input sections — unknown keys fail validation loudly."""

    model_config = ConfigDict(extra="forbid")


# ---- Workflow variants ------------------------------------------------------


class ExploitWorkflowInput(_Strict):
    """Known-vulnerability synthetic workflow."""

    kind: Literal["exploit"] = Field(
        ..., description="Selects the known-vulnerability synthetic workflow."
    )
    synthetic_vuln_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Names a directory under apps/<app>/synthetic_vulnerabilities/. "
            "Required for the exploit workflow."
        ),
    )


class RedteamSyntheticWorkflowInput(_Strict):
    """Bundle-backed redteam against a synthetic vulnerability."""

    kind: Literal["redteam_synthetic"] = Field(
        ..., description="Bundle-backed redteam against a synthetic vulnerability."
    )
    synthetic_vuln_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Names a directory under apps/<app>/synthetic_vulnerabilities/. "
            "The bundle's metadata.json supplies the authoritative attacker_model."
        ),
    )


class RedteamZerodayWorkflowInput(_Strict):
    """Bundle-backed redteam against a zero-day report task."""

    kind: Literal["redteam_zeroday"] = Field(
        ..., description="Bundle-backed redteam against a zero-day task."
    )
    task: str = Field(
        ...,
        min_length=1,
        description=(
            "Names a directory under zerodays/reports/<app>/. The bundle's "
            "metadata.json supplies the authoritative attacker_model."
        ),
    )


class RedteamProbeOnlyWorkflowInput(_Strict):
    """Bundle-less redteam scored only by probes.

    Single baseline replay, no patch, no verifier. ``attacker_model`` is
    authoritative here because there is no task metadata.json to read from.
    """

    kind: Literal["redteam_probe_only"] = Field(
        ..., description="Bundle-less redteam scored by probes only."
    )
    attacker_model: AttackerModel = Field(
        ...,
        description=(
            "Required and authoritative for probe-only mode (no bundle "
            "metadata to read from)."
        ),
    )


WorkflowInput = Annotated[
    Union[
        ExploitWorkflowInput,
        RedteamSyntheticWorkflowInput,
        RedteamZerodayWorkflowInput,
        RedteamProbeOnlyWorkflowInput,
    ],
    Field(discriminator="kind"),
]


# ---- Agent variants ---------------------------------------------------------


class CustomAgentInput(_Strict):
    """In-process custom agent loop."""

    mode: Literal["custom"] = Field(..., description="In-process Python agent loop.")
    image: str = Field(
        ...,
        min_length=1,
        description=(
            "Kali / runtime Docker image for the custom agent "
            "(e.g. cybench/mobilecybench:latest)."
        ),
    )
    model: str = Field(
        ...,
        min_length=1,
        description=(
            "Model id (e.g. gpt-5.5, claude-opus-4-7). Routed via "
            "agent/custom/model_providers/factory.py."
        ),
    )
    max_iterations: int = Field(
        ..., gt=0, description="Maximum agent turns before stopping."
    )
    max_model_response_tokens: int = Field(
        ..., gt=0, description="Per-call output token cap forwarded to the provider."
    )
    llm_request_timeout_ms: int = Field(
        default=600_000,
        gt=0,
        description=(
            "Per-LLM-API-call timeout (milliseconds). Used by the custom "
            "agent for provider calls and for docker exec calls into the kali container."
        ),
    )
    reasoning_effort: Optional[Literal["low", "medium", "high"]] = Field(
        default=None,
        description=(
            "Reasoning effort hint forwarded to providers that accept it. "
            "Models without a reasoning-effort knob ignore this field."
        ),
    )
    allow_unregistered_models: bool = Field(
        default=False,
        description=(
            "Permit models that are not declared in "
            "agent/custom/model_providers/factory.py:SupportedModel. Falls "
            "through to LiteLLM with auto-detected routing and a runtime WARNING."
        ),
    )


class ExternalAgentInput(_Strict):
    """BYO containerized agent."""

    mode: Literal["external"] = Field(
        ..., description="BYO Docker-image agent per BRING_YOUR_OWN_AGENT.md."
    )
    image: str = Field(
        ...,
        min_length=1,
        description=(
            "BYO reference image (e.g. cybench/mobilecybench:codex_0.130.0-r2, "
            ":claudecode_2.1.140-r2, or a lab's own tag)."
        ),
    )
    model: str = Field(
        ...,
        min_length=1,
        description="Model id forwarded verbatim to the in-container CLI.",
    )
    wallclock_seconds: int = Field(
        default=1800,
        gt=0,
        description=(
            "Harness-side wall-clock kill budget for external agents "
            "(SIGKILL on expiry)."
        ),
    )
    reasoning_effort: Optional[Literal["low", "medium", "high"]] = Field(
        default=None,
        description=("Reasoning effort hint forwarded to providers that accept it."),
    )
    allow_unregistered_models: bool = Field(
        default=False,
        description=(
            "Skip the config-load model registration check (image/CLI compat "
            "is still enforced)."
        ),
    )


AgentInput = Annotated[
    Union[CustomAgentInput, ExternalAgentInput],
    Field(discriminator="mode"),
]


# ---- Execution --------------------------------------------------------------


class ExecutionInput(_Strict):
    """Execution mode."""

    mode: Literal["live", "dry_run", "gold"] = Field(
        default="live",
        description=(
            "Execution branch. ``live`` (default): run the agent. "
            "``dry_run``: drop into an interactive Kali shell instead. "
            "``gold``: replay the canonical exploit; invalid for "
            "redteam_probe_only (no canonical source)."
        ),
    )


# ---- Runtime ---------------------------------------------------------------


class RuntimeInput(_Strict):
    """Infrastructure knobs shared across workflows."""

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
    emulator_backend: Literal["native", "container"] = Field(
        default="native",
        description=(
            "Run the emulator as a host process ('native') or as a separate "
            "Docker container ('container', used by GKE)."
        ),
    )
    emulator_display: Literal["headed", "headless"] = Field(
        default="headed", description="Whether the emulator opens a window."
    )
    emulator_boot_timeout_seconds: int = Field(
        default=300,
        gt=0,
        description="How long to wait for the emulator to be ready (seconds).",
    )
    network_mode: Literal["restricted", "permissive"] = Field(
        default="permissive",
        description=(
            "Squid egress policy. 'permissive' (default): any public host. "
            "'restricted': exact-FQDN allowlist (LLM APIs + apt/pip mirrors)."
        ),
    )
    script_timeout: int = Field(
        default=600,
        gt=0,
        description=(
            "Seconds for long-running scripts (exploit, verify, setup, prepare_app)."
        ),
    )
    build_command_timeout: int = Field(
        default=1200, gt=0, description="Seconds for the APK build command."
    )
    apk_timeout: int = Field(
        default=60,
        gt=0,
        description=(
            "HARD wall-clock deadline (seconds) for the malicious-APK replay "
            "to write done.marker; agent cannot extend by withholding it."
        ),
    )


# ---- Prompt -----------------------------------------------------------------


class PromptInput(_Strict):
    """Prompt overrides (decoupled from execution controls)."""

    additional_system_prompt: Optional[str] = Field(
        default=None,
        description=(
            "Free-form text appended to the workflow-built system prompt "
            "(after any per-app additional_info from metadata.json)."
        ),
    )


# ---- Top-level --------------------------------------------------------------


class RunnerConfig(_Strict):
    """Configuration for a single ``runner.py`` invocation.

    Cross-section invariants enforced by validators:

    * ``execution.mode='gold'`` is invalid for ``workflow.kind='redteam_probe_only'``.
    * External-mode ``agent.model`` must be registered (or
      ``allow_unregistered_models=true``).
    * External-mode ``agent.image`` and ``agent.model`` provider must be
      compatible (claudecode_* ↔ anthropic, codex_* ↔ openai); the check is
      not bypassed by ``allow_unregistered_models`` because the constraint is
      a property of the CLI in the image, not of the model registry.

    See ``documentation/EXPERIMENTS.md`` for the prose walkthrough.
    """

    workflow: WorkflowInput = Field(
        ..., description="Pipeline + selectors (discriminated by ``kind``)."
    )
    agent: AgentInput = Field(
        ..., description="Agent integration (discriminated by ``mode``)."
    )
    runtime: RuntimeInput = Field(
        ..., description="Infrastructure knobs (emulator, network, timeouts)."
    )
    execution: ExecutionInput = Field(
        default_factory=lambda: ExecutionInput(mode="live"),
        description="Execution branch (live / dry_run / gold).",
    )
    prompt: PromptInput = Field(
        default_factory=PromptInput, description="Prompt overrides."
    )

    @classmethod
    def from_file(cls, config_path: Path) -> "RunnerConfig":
        config_path = Path(config_path)
        try:
            with open(config_path, "r") as f:
                c_dict = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Runner configuration file not found: {config_path}"
            )
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in config file: {e}")

        # Strip tooling-only keys before validation; the model is strict
        # (``extra='forbid'``) and would reject them otherwise.
        c_dict.pop("$schema", None)
        return cls(**c_dict)

    @model_validator(mode="after")
    def validate_probe_only_execution(self) -> "RunnerConfig":
        """probe-only requires the agent loop to score; ``dry_run`` skips it,
        ``gold`` has no canonical exploit to replay. Reject both early."""
        if isinstance(self.workflow, RedteamProbeOnlyWorkflowInput):
            if self.execution.mode == "gold":
                raise ValueError(
                    "execution.mode='gold' is invalid for redteam_probe_only: "
                    "probe-only has no canonical exploit source to resolve."
                )
            if self.execution.mode == "dry_run":
                raise ValueError(
                    "execution.mode='dry_run' is invalid for redteam_probe_only: "
                    "dry_run drops into an interactive shell and skips scoring entirely."
                )
        return self

    @model_validator(mode="after")
    def validate_model_registered_external(self) -> "RunnerConfig":
        """Reject unknown model ids for external mode.

        Custom mode is gated when the provider is constructed in
        ``agent/custom/model_providers/factory.py:get_model_provider``;
        external mode otherwise forwards the model id verbatim to the
        container CLI, so a typo only fails after image pull + emulator boot.
        ``allow_unregistered_models=True`` bypasses this for exploration runs.
        """
        ag = self.agent
        if not isinstance(ag, ExternalAgentInput) or ag.allow_unregistered_models:
            return self
        if ag.model not in MODEL_REGISTRY:
            raise ValueError(
                f"Unknown model {ag.model!r}. Supported: {sorted(MODEL_REGISTRY)}. "
                "Add to SupportedModel + utils/token_pricing.json, or set "
                "agent.allow_unregistered_models=true. See documentation/ADDING_MODELS.md."
            )
        return self

    @model_validator(mode="after")
    def validate_image_model_compat(self) -> "RunnerConfig":
        """Reject obvious image/model mismatches for external-mode reference CLIs.

        The reference ``claudecode_*`` image only talks to Anthropic and
        ``codex_*`` only to OpenAI. Unknown image tags (lab / BYO) skip — they
        declare their own contract. Unlike model-registry gating, this check
        is not bypassed by ``allow_unregistered_models``: the constraint is a
        property of the CLI in the image, not of the model registry.
        """
        ag = self.agent
        if not isinstance(ag, ExternalAgentInput):
            return self
        cli = _cli_family(ag.image)
        if cli is None:
            return self
        allowed = _CLI_IMAGE_COMPAT[cli]
        rule = lookup_rule(ag.model)
        if rule.provider not in allowed:
            raise ValueError(
                f"agent.image '{ag.image}' uses the {cli} CLI which only "
                f"supports {sorted(allowed)} models; got model={ag.model!r} "
                f"(provider={rule.provider}). Use a model from the supported "
                f"provider(s), or switch agent.image."
            )
        return self

    # ---- Schema export ----

    JSON_SCHEMA_DRAFT: ClassVar[str] = "https://json-schema.org/draft/2020-12/schema"
    JSON_SCHEMA_ID: ClassVar[str] = (
        "https://mobilecybench.dev/schemas/runner_config.schema.json"
    )
    JSON_SCHEMA_TITLE: ClassVar[str] = "Runner Config"

    @classmethod
    def build_json_schema(cls) -> dict[str, Any]:
        body = cls.model_json_schema()
        return {
            "$schema": cls.JSON_SCHEMA_DRAFT,
            "$id": cls.JSON_SCHEMA_ID,
            "title": cls.JSON_SCHEMA_TITLE,
            **{k: v for k, v in body.items() if k != "title"},
        }

    @classmethod
    def render_json_schema(cls) -> str:
        return json.dumps(cls.build_json_schema(), indent=2, ensure_ascii=False) + "\n"
