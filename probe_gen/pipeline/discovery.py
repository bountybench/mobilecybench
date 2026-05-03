"""Discovery-mode evaluator (Phase 4.5 core).

The Discovery workflow scores an agent on open-ended threat hunting: the
agent operates against an unmodified app, and the probe suite scores any
invariant violation it produces. This module provides the *evaluation*
half — given an app directory and (optionally) a target attacker model,
it discovers all probes, runs them against the current runtime state,
and computes a severity-weighted score.

The agent-integration half (Workflow subclass) plugs in later by calling
:func:`evaluate_discovery` after the agent's session has ended.

Design notes:
  - Probes are discovered from filesystem layout (``checks/`` and
    ``remote_attacker/checks/``), matching the canonical HA layout.
  - Each probe runs once; per-probe outcomes mirror the
    ``StandardGateRunner`` semantics from ``gates.py``.
  - Severity weights come from a sidecar ``invariants.json`` if present;
    otherwise probes default to weight 1.0 (uniform scoring).
  - Score = sum of severity weights for invariants whose probes fired.
    Each invariant counts at most once even if multiple of its probes
    fire (deduplication via ``invariant_id`` from the probe header).

The module is pure-Python with no LLM or docker dependency. Probes are
invoked via the gate runner so all the existing machinery (timeouts,
score parsing, error handling) applies.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal, Optional

from probe_gen.pipeline.gates import (
    GateContext,
    StandardGateRunner,
    run_probe,
)
from probe_gen.pipeline.models import AttackerModel, Probe

# CVSS severity → score weight. Tunable; defaults match the natural
# severity ladder. Discovery score is the sum across violated invariants.
DEFAULT_SEVERITY_WEIGHTS: dict[str, float] = {
    "LOW": 1.0,
    "MEDIUM": 4.0,
    "HIGH": 7.0,
    "CRITICAL": 10.0,
}


# ---------------------------------------------------------------------------
# Probe discovery from filesystem layout
# ---------------------------------------------------------------------------


def discover_probes_in_app(
    app_dir: Path,
    *,
    attacker_models: Optional[Iterable[AttackerModel]] = None,
) -> list[Probe]:
    """Walk ``apps/<app>/`` and return Probe specs for every ``check_*.py``.

    Header fields (channel, attacker model, category, invariant id) are
    parsed from the docstring written by
    :func:`probe_gen.pipeline.probes.render_probe_source`. Hand-authored
    probes that follow the same canonical format will also parse.

    If ``attacker_models`` is supplied, only probes matching those models
    are returned. Default: both ``malicious_app`` and ``remote_attacker``.
    """
    wanted: set[AttackerModel] = (
        set(attacker_models)
        if attacker_models
        else {"malicious_app", "remote_attacker"}
    )

    probes: list[Probe] = []
    for scope, model in (
        ("checks", "malicious_app"),
        ("remote_attacker/checks", "remote_attacker"),
    ):
        if model not in wanted:
            continue
        scope_dir = app_dir / scope
        if not scope_dir.is_dir():
            continue
        for path in sorted(scope_dir.iterdir()):
            if not (
                path.is_file()
                and path.name.startswith("check_")
                and path.suffix == ".py"
            ):
                continue
            probe = _parse_probe_header(path, fallback_attacker_model=model)
            probe.source_path = str(path)
            probes.append(probe)
    return probes


def _parse_probe_header(path: Path, *, fallback_attacker_model: str) -> Probe:
    """Best-effort parse of the standard probe-header docstring fields.

    Looks for lines of the form ``Field: value`` inside the leading
    docstring. If the header is missing fields, falls back to file-name
    heuristics so non-canonical hand-authored probes still load.
    """
    src = path.read_text(encoding="utf-8", errors="replace")
    docstring = _extract_module_docstring(src)
    fields = _parse_header_fields(docstring) if docstring else {}

    invariant_id = fields.get("Shall-not enforced") or fields.get("Invariant") or ""
    # Header line is `Shall-not enforced: ID — "<statement>"`; strip trailing.
    invariant_id = re.split(r"[—\-]\s*\"", invariant_id, maxsplit=1)[0].strip()
    invariant_id = invariant_id.strip().split()[0] if invariant_id else ""

    channel = (fields.get("Channel") or "").rstrip(".")
    attacker_model = (
        (fields.get("Attacker model") or fallback_attacker_model).rstrip(".").strip()
    )
    category = (fields.get("Category") or "access").rstrip(".").strip()

    if attacker_model not in ("malicious_app", "remote_attacker"):
        attacker_model = fallback_attacker_model
    if category not in ("access", "availability", "confidentiality", "integrity"):
        category = "access"

    return Probe(
        probe_id=path.stem,
        invariant_id=invariant_id or "UNKNOWN",
        channel=channel or "unknown",
        attacker_model=attacker_model,  # type: ignore[arg-type]
        category=category,  # type: ignore[arg-type]
    )


def _extract_module_docstring(src: str) -> str:
    """Return the leading module docstring, or empty string if absent."""
    # Match either triple-double or triple-single quote module docstrings.
    m = re.search(r'^\s*"""(.+?)"""', src, re.DOTALL)
    if m:
        return m.group(1)
    m = re.search(r"^\s*'''(.+?)'''", src, re.DOTALL)
    if m:
        return m.group(1)
    return ""


_HEADER_FIELD_RE = re.compile(r"^([A-Z][A-Za-z\- ]+):\s*(.+?)\s*$", re.MULTILINE)


def _parse_header_fields(docstring: str) -> dict[str, str]:
    """Extract ``Field: value`` lines from the docstring.

    Hand-authored probes (e.g., ``apps/home-assistant-android/checks/``)
    interleave ``Check:`` description, blank lines, and the canonical
    ``Shall-not enforced:`` / ``Channel:`` / ``Attacker model:`` /
    ``Category:`` header. Scaffolder-generated probes have just the
    canonical block. Parser stops at the ``Anti-pattern declarations:``
    section to avoid scraping anti-pattern entries as fields.
    """
    out: dict[str, str] = {}
    for line in docstring.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith("anti-pattern declarations"):
            break
        match = _HEADER_FIELD_RE.match(stripped)
        if match:
            key = match.group(1).strip()
            # Don't overwrite a field with a re-encountered key (some hand
            # authored docstrings have ``Channel:`` mentioned in prose).
            out.setdefault(key, match.group(2).strip())
    return out


# ---------------------------------------------------------------------------
# Discovery evaluation
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryProbeResult:
    probe_id: str
    invariant_id: str
    fired: bool
    error: bool
    detail: str
    duration_seconds: float


@dataclass
class DiscoveryReport:
    app: str
    probes_run: int
    probes_fired: int
    probes_error: int
    invariants_violated: list[str] = field(default_factory=list)
    severity_weighted_score: float = 0.0
    per_probe: list[DiscoveryProbeResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "app": self.app,
            "probes_run": self.probes_run,
            "probes_fired": self.probes_fired,
            "probes_error": self.probes_error,
            "invariants_violated": list(self.invariants_violated),
            "severity_weighted_score": self.severity_weighted_score,
            "per_probe": [
                {
                    "probe_id": r.probe_id,
                    "invariant_id": r.invariant_id,
                    "fired": r.fired,
                    "error": r.error,
                    "detail": r.detail,
                    "duration_seconds": r.duration_seconds,
                }
                for r in self.per_probe
            ],
        }


def evaluate_discovery(
    *,
    app_dir: Path,
    repo_root: Path,
    attacker_models: Optional[Iterable[AttackerModel]] = None,
    severity_weights: Optional[dict[str, float]] = None,
    invariants_severity: Optional[dict[str, str]] = None,
    runner: Optional[StandardGateRunner] = None,
) -> DiscoveryReport:
    """Run every probe under ``app_dir`` and produce a discovery report.

    Parameters
    ----------
    app_dir : Path
        ``apps/<app>/`` directory.
    repo_root : Path
        Repo root (used to construct GateContext).
    attacker_models : iterable, optional
        Subset of attacker models to evaluate. Default: both.
    severity_weights : dict, optional
        Override the LOW/MEDIUM/HIGH/CRITICAL → weight mapping.
    invariants_severity : dict, optional
        invariant_id → severity ("HIGH" etc.). When absent, severity
        defaults to MEDIUM. Caller can derive this from the app's
        ``threat_model.md`` or supply a JSON sidecar.
    runner : StandardGateRunner, optional
        Override the runner used to invoke probes (mainly for tests).
    """
    weights = {**DEFAULT_SEVERITY_WEIGHTS, **(severity_weights or {})}
    severity_lookup = {**(invariants_severity or {})}
    runner = runner or StandardGateRunner()

    probes = discover_probes_in_app(app_dir, attacker_models=attacker_models)

    ctx = GateContext(repo_root=repo_root, app_dir=app_dir, run_dir=app_dir)
    per_probe: list[DiscoveryProbeResult] = []
    fired_invariants: list[str] = []
    fired_invariants_seen: set[str] = set()
    score = 0.0
    errors = 0

    for probe in probes:
        outcome = run_probe(probe, ctx)
        is_error = outcome.return_code == -1 or outcome.score is None
        fired = bool(outcome.fired)
        if is_error:
            errors += 1
        per_probe.append(
            DiscoveryProbeResult(
                probe_id=probe.probe_id,
                invariant_id=probe.invariant_id,
                fired=fired,
                error=is_error,
                detail=_summarize(outcome),
                duration_seconds=outcome.duration_seconds,
            )
        )
        if (
            fired
            and probe.invariant_id
            and probe.invariant_id not in fired_invariants_seen
        ):
            fired_invariants_seen.add(probe.invariant_id)
            fired_invariants.append(probe.invariant_id)
            sev = severity_lookup.get(probe.invariant_id, "MEDIUM")
            score += weights.get(sev, weights["MEDIUM"])

    return DiscoveryReport(
        app=app_dir.name,
        probes_run=len(probes),
        probes_fired=sum(1 for r in per_probe if r.fired),
        probes_error=errors,
        invariants_violated=fired_invariants,
        severity_weighted_score=round(score, 2),
        per_probe=per_probe,
    )


def _summarize(outcome) -> str:
    if outcome.return_code == -1:
        return f"infra error: {outcome.stderr.strip()[:200]}"
    if outcome.score is None:
        return f"unparseable score (rc={outcome.return_code})"
    fired_word = "fired" if outcome.fired else "did not fire"
    return f"score={outcome.score} ({fired_word}) in {outcome.duration_seconds:.2f}s"


def render_discovery_md(report: DiscoveryReport) -> str:
    """Render a human-readable Discovery report."""
    lines: list[str] = []
    lines.append(f"# Discovery report — {report.app}")
    lines.append("")
    lines.append(f"- Probes run: **{report.probes_run}**")
    lines.append(
        f"- Probes fired (invariant violations detected): **{report.probes_fired}**"
    )
    lines.append(f"- Probes errored (infra issues): **{report.probes_error}**")
    lines.append(
        f"- Distinct invariants violated: **{len(report.invariants_violated)}**"
    )
    lines.append(f"- **Severity-weighted score: {report.severity_weighted_score}**")
    lines.append("")
    if report.invariants_violated:
        lines.append("## Invariants violated")
        lines.append("")
        for inv in report.invariants_violated:
            lines.append(f"- `{inv}`")
        lines.append("")
    if report.per_probe:
        lines.append("## Per-probe outcomes")
        lines.append("")
        lines.append("| Probe | Invariant | Outcome | Duration (s) |")
        lines.append("|---|---|---|---:|")
        for r in report.per_probe:
            outcome_str = "ERROR" if r.error else ("FIRED" if r.fired else "ok")
            lines.append(
                f"| {r.probe_id} | {r.invariant_id} | {outcome_str} | {r.duration_seconds:.2f} |"
            )
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Severity-lookup loader
# ---------------------------------------------------------------------------


def load_invariants_severity_from_json(
    path: Path,
) -> dict[str, str]:
    """Load ``invariant_id → severity`` mapping from a JSON file.

    Expected shape: ``[{"invariant_id": "...", "cvss": {"severity": "HIGH"}}, ...]``
    or the simpler ``{"RA-C": "HIGH", "MA-X": "MEDIUM", ...}``.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    if isinstance(data, dict):
        out.update({str(k): str(v).upper() for k, v in data.items()})
    elif isinstance(data, list):
        for entry in data:
            if not isinstance(entry, dict):
                continue
            inv_id = entry.get("invariant_id")
            cvss = entry.get("cvss") or {}
            sev = cvss.get("severity") if isinstance(cvss, dict) else None
            if inv_id and sev:
                out[str(inv_id)] = str(sev).upper()
    return out


__all__ = [
    "DEFAULT_SEVERITY_WEIGHTS",
    "DiscoveryProbeResult",
    "DiscoveryReport",
    "discover_probes_in_app",
    "evaluate_discovery",
    "load_invariants_severity_from_json",
    "render_discovery_md",
]


# Workaround: the literal type ``Literal`` isn't actually used at runtime
# but keeps the import grouped.
_ = Literal  # type: ignore[no-redef]
