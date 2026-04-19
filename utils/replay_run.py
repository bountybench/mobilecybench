"""Replay a prior agent's exploit through the standard redteam pipeline.

One source of truth: the source run's `run_summary.json`. No fallbacks.
Only the saved `agent_exploit/` bytes are reused — task bundle, APKs, and
verifier all come from the current workspace.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

AGENT_EXPLOIT_DIR = "agent_exploit"

_REQUIRED_FILES = {
    "malicious_app": ("exploit_apk/AndroidManifest.xml",),
    "auth_attacker": ("exploit.sh",),
}


class ReplayRunError(Exception):
    """Replay-run preflight failure."""


@dataclass(frozen=True)
class ReplaySource:
    source_dir: Path
    app_name: str
    task: str
    attack_model: str

    @property
    def agent_exploit_dir(self) -> Path:
        return self.source_dir / AGENT_EXPLOIT_DIR


def load_replay_source(replay_run: str, project_root: Path) -> ReplaySource:
    """Resolve `--replay-run <path>` to a validated ReplaySource.

    Reads exactly one file: `<source>/run_summary.json`. Raises
    ReplayRunError with a human-actionable message if anything is missing
    or the on-disk exploit shape does not match the recorded attack_model.
    """
    source_dir = _resolve_source_dir(replay_run, project_root)
    summary_path = source_dir / "run_summary.json"
    if not summary_path.is_file():
        raise ReplayRunError(
            f"Replay source missing {summary_path.name}: {summary_path}. "
            "The source run never completed metadata capture and cannot be replayed."
        )

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ReplayRunError(f"Replay source has malformed run_summary.json: {e}")

    ctx = summary.get("context") or {}
    snap = (summary.get("config") or {}).get("full_snapshot") or {}

    workflow = ctx.get("workflow")
    if workflow != "redteam":
        raise ReplayRunError(
            f"Replay source workflow is {workflow!r}; only 'redteam' is supported."
        )

    values = {
        "app_name": ctx.get("app_name"),
        "task": snap.get("task"),
        "attack_model": snap.get("attack_model"),
    }
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise ReplayRunError(
            f"Replay source run_summary.json is missing required fields: {missing}."
        )
    if values["attack_model"] not in _REQUIRED_FILES:
        raise ReplayRunError(
            f"Unknown attack_model {values['attack_model']!r} in replay source."
        )

    _validate_exploit_shape(source_dir / AGENT_EXPLOIT_DIR, values["attack_model"])
    return ReplaySource(
        source_dir=source_dir,
        app_name=str(values["app_name"]),
        task=str(values["task"]),
        attack_model=str(values["attack_model"]),
    )


def stage_replay_exploit(
    source: ReplaySource, logs_dir: Path, project_root: Path
) -> Path:
    """Copy the source agent_exploit/ into the current run's logs dir.

    For malicious_app, also injects the canonical build script from
    templates/ so the replayed project builds with the current script.
    Returns the staged target directory.
    """
    target = logs_dir / AGENT_EXPLOIT_DIR
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source.agent_exploit_dir, target)

    if source.attack_model == "malicious_app":
        canonical = project_root / "templates" / "malicious_app" / "build_exploit_apk.sh"
        if not canonical.is_file():
            raise ReplayRunError(f"Canonical build script missing: {canonical}")
        dst = target / "exploit_apk" / "build_exploit_apk.sh"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(canonical, dst)
        dst.chmod(dst.stat().st_mode | 0o111)
    else:  # auth_attacker
        sh = target / "exploit.sh"
        sh.chmod(sh.stat().st_mode | 0o111)

    return target


def _resolve_source_dir(replay_run: str, project_root: Path) -> Path:
    p = Path(replay_run).expanduser()
    for candidate in (p, project_root / p):
        if candidate.exists():
            if not candidate.is_dir():
                raise ReplayRunError(
                    f"Replay source is not a directory: {candidate}"
                )
            return candidate.resolve()
    raise ReplayRunError(
        f"Replay source not found: {replay_run}. "
        "Pass a logs/experiment_<uuid> directory."
    )


def _validate_exploit_shape(agent_exploit: Path, attack_model: str) -> None:
    if not agent_exploit.is_dir():
        raise ReplayRunError(
            f"No agent_exploit/ under replay source at {agent_exploit}. "
            "The source run ended before the agent submitted an exploit."
        )
    for rel in _REQUIRED_FILES[attack_model]:
        if not (agent_exploit / rel).is_file():
            raise ReplayRunError(
                f"Replay source invalid for attack_model={attack_model!r}: "
                f"missing {rel}"
            )
    if attack_model == "malicious_app":
        src_dir = agent_exploit / "exploit_apk" / "src"
        if not src_dir.is_dir() or not any(src_dir.rglob("*.java")):
            raise ReplayRunError(
                "Replay source invalid for malicious_app: "
                "no Java sources under exploit_apk/src/"
            )
