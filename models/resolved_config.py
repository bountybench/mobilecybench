"""Resolved runner config: the typed object runtime code consumes.

``RunnerConfig`` is the public input contract; ``ResolvedRunnerConfig`` is
what the runner, workflows, agent construction, and BYO task creation read.
Resolution reads bundle-backed ``attacker_model`` from task metadata and
attaches the resolved :class:`TaskBundle` directly to each redteam variant
(no separate carrier — the bundle is a structural property of "redteam").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional, Union

from evaluation.task_bundle import (
    ProbeOnlyBundle,
    SyntheticBundle,
    TaskBundle,
    ZerodayBundle,
    assert_zerodays_initialized,
)
from models.config import (
    AttackerModel,
    CustomAgentInput,
    ExploitWorkflowInput,
    ExternalAgentInput,
    RedteamProbeOnlyWorkflowInput,
    RedteamSyntheticWorkflowInput,
    RedteamZerodayWorkflowInput,
    RunnerConfig,
)

# ---- Workflow variants -------------------------------------------------------


@dataclass(frozen=True)
class ResolvedExploitWorkflow:
    synthetic_vuln_id: str
    kind: Literal["exploit"] = field(default="exploit", init=False)


@dataclass(frozen=True)
class ResolvedRedteamSyntheticWorkflow:
    synthetic_vuln_id: str
    attacker_model: AttackerModel
    bundle: TaskBundle
    kind: Literal["redteam_synthetic"] = field(default="redteam_synthetic", init=False)


@dataclass(frozen=True)
class ResolvedRedteamZerodayWorkflow:
    task: str
    attacker_model: AttackerModel
    bundle: TaskBundle
    kind: Literal["redteam_zeroday"] = field(default="redteam_zeroday", init=False)


@dataclass(frozen=True)
class ResolvedRedteamProbeOnlyWorkflow:
    attacker_model: AttackerModel
    bundle: TaskBundle
    kind: Literal["redteam_probe_only"] = field(
        default="redteam_probe_only", init=False
    )


ResolvedWorkflow = Union[
    ResolvedExploitWorkflow,
    ResolvedRedteamSyntheticWorkflow,
    ResolvedRedteamZerodayWorkflow,
    ResolvedRedteamProbeOnlyWorkflow,
]

# Type alias for any redteam variant — use in annotations.
ResolvedRedteamWorkflow = Union[
    ResolvedRedteamSyntheticWorkflow,
    ResolvedRedteamZerodayWorkflow,
    ResolvedRedteamProbeOnlyWorkflow,
]

# Tuple form for ``isinstance(wf, REDTEAM_WORKFLOW_TYPES)``. Pyright narrows
# on the tuple just like a Union.
REDTEAM_WORKFLOW_TYPES = (
    ResolvedRedteamSyntheticWorkflow,
    ResolvedRedteamZerodayWorkflow,
    ResolvedRedteamProbeOnlyWorkflow,
)


# ---- Agent variants ----------------------------------------------------------


@dataclass(frozen=True)
class ResolvedCustomAgent:
    image: str
    model: str
    max_iterations: int
    max_model_response_tokens: int
    llm_request_timeout_ms: int
    reasoning_effort: Optional[Literal["low", "medium", "high"]]
    allow_unregistered_models: bool
    mode: Literal["custom"] = field(default="custom", init=False)


@dataclass(frozen=True)
class ResolvedExternalAgent:
    image: str
    model: str
    wallclock_seconds: int
    reasoning_effort: Optional[Literal["low", "medium", "high"]]
    allow_unregistered_models: bool
    mode: Literal["external"] = field(default="external", init=False)


ResolvedAgent = Union[ResolvedCustomAgent, ResolvedExternalAgent]


# ---- Other sections ----------------------------------------------------------


@dataclass(frozen=True)
class ResolvedRuntime:
    build_type: Literal["source", "download-apk", "skip-apk"]
    no_codebase: bool
    emulator_backend: Literal["native", "container"]
    emulator_display: Literal["headed", "headless"]
    emulator_boot_timeout_seconds: int
    network_mode: Literal["restricted", "permissive"]
    script_timeout: int
    build_command_timeout: int
    apk_timeout: int


# ---- Top-level ---------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedRunnerConfig:
    app_name: str
    workflow: ResolvedWorkflow
    agent: ResolvedAgent
    runtime: ResolvedRuntime
    execution_mode: Literal["live", "dry_run", "gold"]
    additional_system_prompt: Optional[str]

    @property
    def is_redteam(self) -> bool:
        return self.workflow.kind != "exploit"

    @property
    def workflow_family(self) -> Literal["exploit", "redteam"]:
        """Coarse family (``exploit`` or ``redteam``) for routing score files
        and the top-level ``workflow`` slot in ``run_summary.json``."""
        return "exploit" if self.workflow.kind == "exploit" else "redteam"

    @property
    def is_probe_only(self) -> bool:
        return self.workflow.kind == "redteam_probe_only"

    def summary_view(self) -> dict:
        """Structured projection for ``run_summary.config.effective``.

        Single canonical walker over the resolved object — ``log_view`` is a
        format of this. Variant-specific fields appear only on the matching
        variant (no ``None`` placeholders, no bundle objects).
        """
        wf = self.workflow
        wf_dict: dict = {"kind": wf.kind}
        if isinstance(wf, (ResolvedExploitWorkflow, ResolvedRedteamSyntheticWorkflow)):
            wf_dict["synthetic_vuln_id"] = wf.synthetic_vuln_id
        if isinstance(wf, ResolvedRedteamZerodayWorkflow):
            wf_dict["task"] = wf.task
        if isinstance(wf, REDTEAM_WORKFLOW_TYPES):
            wf_dict["attacker_model"] = wf.attacker_model

        ag = self.agent
        ag_dict: dict = {
            "mode": ag.mode,
            "model": ag.model,
            "image": ag.image,
            "reasoning_effort": ag.reasoning_effort,
            "allow_unregistered_models": ag.allow_unregistered_models,
        }
        if isinstance(ag, ResolvedCustomAgent):
            ag_dict["max_iterations"] = ag.max_iterations
            ag_dict["max_model_response_tokens"] = ag.max_model_response_tokens
            ag_dict["llm_request_timeout_ms"] = ag.llm_request_timeout_ms
        else:
            ag_dict["wallclock_seconds"] = ag.wallclock_seconds

        rt = self.runtime
        return {
            "app_name": self.app_name,
            "workflow": wf_dict,
            "agent": ag_dict,
            "execution": {"mode": self.execution_mode},
            "runtime": {
                "build_type": rt.build_type,
                "no_codebase": rt.no_codebase,
                "emulator_backend": rt.emulator_backend,
                "emulator_display": rt.emulator_display,
                "emulator_boot_timeout_seconds": rt.emulator_boot_timeout_seconds,
                "network_mode": rt.network_mode,
                "script_timeout": rt.script_timeout,
                "build_command_timeout": rt.build_command_timeout,
                "apk_timeout": rt.apk_timeout,
            },
            "prompt": {"additional_system_prompt": self.additional_system_prompt},
        }

    def log_view(self) -> list[str]:
        """Compact ``experiment.log`` lines — a format of :meth:`summary_view`."""
        view = self.summary_view()
        wf = view["workflow"]
        wf_extras = " ".join(f"{k}={v}" for k, v in wf.items() if k != "kind")
        wf_line = f"workflow={wf['kind']}" + (f" {wf_extras}" if wf_extras else "")

        ag = view["agent"]
        if ag["mode"] == "custom":
            ag_line = (
                f"agent=custom model={ag['model']} iterations={ag['max_iterations']}"
            )
        else:
            ag_line = (
                f"agent=external image={ag['image']} model={ag['model']} "
                f"wallclock_seconds={ag['wallclock_seconds']}"
            )
        if ag["reasoning_effort"]:
            ag_line += f" reasoning={ag['reasoning_effort']}"

        rt = view["runtime"]
        rt_line = (
            f"runtime build={rt['build_type']} "
            f"codebase={'apk-only' if rt['no_codebase'] else 'mounted'} "
            f"emulator={rt['emulator_backend']}/{rt['emulator_display']} "
            f"network={rt['network_mode']}"
        )

        return [
            f"Run config: app={view['app_name']} {wf_line}",
            ag_line,
            f"execution={view['execution']['mode']}",
            rt_line,
        ]


# ---- Resolution --------------------------------------------------------------


def _resolve_workflow(
    config: RunnerConfig, *, app_name: str, project_root: Path
) -> ResolvedWorkflow:
    """Build the workflow variant + attach its bundle (redteam only).

    For redteam_synthetic / redteam_zeroday, the bundle's metadata.json is
    the authoritative source of ``attacker_model``.
    """
    wf = config.workflow
    app_dir = project_root / "apps" / app_name

    if isinstance(wf, ExploitWorkflowInput):
        return ResolvedExploitWorkflow(synthetic_vuln_id=wf.synthetic_vuln_id)

    if isinstance(wf, RedteamProbeOnlyWorkflowInput):
        return ResolvedRedteamProbeOnlyWorkflow(
            attacker_model=wf.attacker_model,
            bundle=ProbeOnlyBundle(app_dir=app_dir, _attacker_model=wf.attacker_model),
        )

    if isinstance(wf, RedteamZerodayWorkflowInput):
        assert_zerodays_initialized(project_root)
        bundle = ZerodayBundle(
            project_root=project_root, app_name=app_name, task=wf.task
        )
        return ResolvedRedteamZerodayWorkflow(
            task=wf.task,
            attacker_model=bundle.attacker_model(),
            bundle=bundle,
        )

    if not isinstance(wf, RedteamSyntheticWorkflowInput):
        raise TypeError(f"unhandled workflow input variant: {type(wf).__name__}")
    s_bundle = SyntheticBundle(app_dir=app_dir, vuln_id=wf.synthetic_vuln_id)
    return ResolvedRedteamSyntheticWorkflow(
        synthetic_vuln_id=wf.synthetic_vuln_id,
        attacker_model=s_bundle.attacker_model(),
        bundle=s_bundle,
    )


def _resolve_agent(config: RunnerConfig) -> ResolvedAgent:
    ag = config.agent
    if isinstance(ag, CustomAgentInput):
        return ResolvedCustomAgent(
            image=ag.image,
            model=ag.model,
            max_iterations=ag.max_iterations,
            max_model_response_tokens=ag.max_model_response_tokens,
            llm_request_timeout_ms=ag.llm_request_timeout_ms,
            reasoning_effort=ag.reasoning_effort,
            allow_unregistered_models=ag.allow_unregistered_models,
        )
    if not isinstance(ag, ExternalAgentInput):
        raise TypeError(f"unhandled agent input variant: {type(ag).__name__}")
    return ResolvedExternalAgent(
        image=ag.image,
        model=ag.model,
        wallclock_seconds=ag.wallclock_seconds,
        reasoning_effort=ag.reasoning_effort,
        allow_unregistered_models=ag.allow_unregistered_models,
    )


def resolve_runner_config(
    config: RunnerConfig, *, app_name: str, project_root: Path
) -> ResolvedRunnerConfig:
    """Resolve the nested input contract into the runtime DI object."""
    rt = config.runtime
    return ResolvedRunnerConfig(
        app_name=app_name,
        workflow=_resolve_workflow(
            config, app_name=app_name, project_root=project_root
        ),
        agent=_resolve_agent(config),
        runtime=ResolvedRuntime(
            build_type=rt.build_type,
            no_codebase=rt.no_codebase,
            emulator_backend=rt.emulator_backend,
            emulator_display=rt.emulator_display,
            emulator_boot_timeout_seconds=rt.emulator_boot_timeout_seconds,
            network_mode=rt.network_mode,
            script_timeout=rt.script_timeout,
            build_command_timeout=rt.build_command_timeout,
            apk_timeout=rt.apk_timeout,
        ),
        execution_mode=config.execution.mode,
        additional_system_prompt=config.prompt.additional_system_prompt,
    )
