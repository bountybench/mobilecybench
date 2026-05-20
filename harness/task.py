"""Python-side producer for the BYO task contract (schemas/task.schema.json)."""

from __future__ import annotations

from typing import Any

from models.resolved_config import (
    REDTEAM_WORKFLOW_TYPES,
    ResolvedExploitWorkflow,
    ResolvedExternalAgent,
    ResolvedRedteamSyntheticWorkflow,
    ResolvedRunnerConfig,
)
from utils.json_io import load_validator

_TASK_VALIDATOR = load_validator("task.schema.json")


def build_task_dict(
    *,
    resolved: ResolvedRunnerConfig,
    external_agent: ResolvedExternalAgent,
    metadata: dict[str, Any],
    app_name: str,
    prompt: str,
    run_id: str,
    apk_relpath: str,
) -> dict[str, Any]:
    """Assemble + schema-validate the task.json dict for an external agent.

    ``external_agent`` is required-typed so the caller's ``isinstance`` narrow
    flows through — no internal mode check.

    Raises ``jsonschema.ValidationError`` on contract violation.
    """
    wf = resolved.workflow
    vuln_id = (
        wf.synthetic_vuln_id
        if isinstance(wf, (ResolvedExploitWorkflow, ResolvedRedteamSyntheticWorkflow))
        else None
    )
    attacker_model = wf.attacker_model if isinstance(wf, REDTEAM_WORKFLOW_TYPES) else ""

    task: dict[str, Any] = {
        "run_id": run_id,
        "app_name": app_name,
        "workflow": resolved.workflow_family,
        "package_name": metadata["package_name"],
        "app_server": metadata.get("app_server") or "",
        "emulator_server": metadata.get("emulator_server") or "",
        "vuln_id": vuln_id,
        "apk_relpath": apk_relpath,
        "no_codebase": resolved.runtime.no_codebase,
        "attacker_model": attacker_model,
        "model": external_agent.model,
        "prompt": prompt,
        "agent_wallclock_seconds": external_agent.wallclock_seconds,
        "reasoning_effort": external_agent.reasoning_effort,
    }
    _TASK_VALIDATOR.validate(task)
    return task
