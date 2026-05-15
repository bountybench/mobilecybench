"""Build the on-disk ``/app/task.json`` shape from operator inputs.

Single source of truth for the task contract is ``schemas/task.schema.json``;
this module is the Python-side producer that the harness invokes before
handing off to an external agent (see ``harness.byo_agent.run_agent``).

The result is validated against the schema before return so labs receive a
clean ``jsonschema.ValidationError`` (with full JSON Pointer) instead of a
KeyError deep inside the agent at runtime.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

# Schema lives at <repo>/schemas/; this module is <repo>/harness/. One parent up.
_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "task.schema.json"

with _SCHEMA_PATH.open() as _f:
    _TASK_SCHEMA: dict[str, Any] = json.load(_f)

_TASK_VALIDATOR = jsonschema.Draft202012Validator(_TASK_SCHEMA)


def build_task_dict(
    *,
    config: Any,
    metadata: dict[str, Any],
    app_name: str,
    prompt: str,
    run_id: str,
    apk_relpath: str,
) -> dict[str, Any]:
    """Assemble the task.json dict for an external agent.

    Args:
        config: ``RunnerConfig`` instance (duck-typed; field reads only).
        metadata: Per-app metadata dict (``app_server``, ``emulator_server``,
            ``package_name``).
        app_name: App under test.
        prompt: Fully assembled workflow prompt (workflow + per-app metadata +
            operator's ``additional_system_prompt``). Test credentials are
            embedded here by the workflow's prompt builder; this function
            does not touch them.
        run_id: Stable identifier for the run (``logger_manager.get_run_id()``).
        apk_relpath: Path to the built target APK, relative to ``/app/codebase``
            (or ``/app/apk`` when ``no_codebase=True``).

    Returns:
        A dict matching ``schemas/task.schema.json``, validated.

    Raises:
        jsonschema.ValidationError: If the resulting dict violates the schema.
    """
    task: dict[str, Any] = {
        "run_id": run_id,
        "app_name": app_name,
        "workflow": config.workflow,
        "package_name": metadata["package_name"],
        "app_server": metadata.get("app_server") or "",
        "emulator_server": metadata.get("emulator_server") or "",
        "vuln_id": config.synthetic_vuln_id,
        "apk_relpath": apk_relpath,
        "no_codebase": config.no_codebase,
        "attacker_model": config.attacker_model or "",
        "model": config.model,
        "prompt": prompt,
        # NOTE: field rename `agent_timeout` -> `agent_wallclock_seconds`
        # lands in the dispatch-wiring commit (§4.3); until then we read the
        # legacy field name and emit the contract-canonical name.
        "agent_wallclock_seconds": config.agent_timeout,
        "reasoning_effort": config.reasoning_effort,
        "screenshot_mode": getattr(config, "screenshot_mode", None),
    }

    _TASK_VALIDATOR.validate(task)
    return task
