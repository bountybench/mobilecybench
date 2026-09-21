"""Top-level pipeline runner.

Wires the data layer (``models``, ``archetypes``), source generators
(``probes``), gates, and coverage matrix together. Persists a
``ProbeGenRun`` to ``probe_gen/runs/<run_id>/`` with verbose subdirs and
a concise ``summary.md``.

Two entry points today:

  - :func:`run_gate_suite` — given a set of invariants + probes already on
    disk, run a sequence of gates and persist the result. No LLM needed.
  - :func:`render_run_summary_md` — pure renderer for the human-readable
    summary, callable on any ``ProbeGenRun`` object.

Future entry points (LLM-dependent, deferred until SDK wiring lands):

  - ``run_full_app_onboarding`` — Phase 1 end-to-end for one app.
  - ``run_probe_synthesis_for_invariant`` — Phase 1.4 + 2.5 for one invariant.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable, Optional

from probe_gen.pipeline.gates import (
    GateContext,
    GateRunner,
    SetupHook,
    StandardGateRunner,
    noop_setup,
)
from probe_gen.pipeline.models import (
    GateName,
    Invariant,
    Probe,
    ProbeGenRun,
)


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def make_run_id(app: str, label: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = label.replace("/", "__").replace("\\", "__") if label else "run"
    return f"{safe_label}_{app}_{ts}"


def run_gate_suite(
    *,
    app: str,
    invariants: Iterable[Invariant],
    probes: Iterable[Probe],
    gate_sequence: Iterable[tuple[GateName, SetupHook]],
    ctx: GateContext,
    runner: Optional[GateRunner] = None,
    label: str = "gates",
    write_to_disk: bool = True,
) -> ProbeGenRun:
    """Run a sequence of (gate, setup) pairs against the given probes.

    Each gate gets the full probe set; semantics in ``StandardGateRunner``
    decide pass/fail. Result is captured in a ``ProbeGenRun``.

    If ``write_to_disk`` is true, persists ``summary.json`` and
    ``summary.md`` under ``ctx.run_dir``.
    """
    runner = runner or StandardGateRunner()
    invariants_list = list(invariants)
    probes_list = list(probes)
    run = ProbeGenRun(
        run_id=make_run_id(app, label),
        app=app,
        started_at_iso=_now_iso(),
        invariants_proposed=invariants_list,
        probes_proposed=probes_list,
    )

    for gate, setup in gate_sequence:
        results = runner.run(gate, probes_list, ctx, setup=setup)
        run.gate_results.extend(results)

    run.ended_at_iso = _now_iso()

    if write_to_disk:
        ctx.run_dir.mkdir(parents=True, exist_ok=True)
        (ctx.run_dir / "summary.json").write_text(
            json.dumps(run.to_dict(), indent=2, default=_default_json), encoding="utf-8"
        )
        (ctx.run_dir / "summary.md").write_text(
            render_run_summary_md(run), encoding="utf-8"
        )

    return run


def render_run_summary_md(run: ProbeGenRun) -> str:
    lines: list[str] = []
    lines.append(f"# Probe-gen run: {run.run_id}")
    lines.append("")
    lines.append(f"- App: **{run.app}**")
    lines.append(f"- Started: `{run.started_at_iso}`")
    lines.append(f"- Ended: `{run.ended_at_iso or '<in progress>'}`")
    lines.append(f"- Invariants proposed: {len(run.invariants_proposed)}")
    lines.append(f"- Probes proposed: {len(run.probes_proposed)}")
    lines.append(f"- Synthetic vulns proposed: {len(run.synthetic_vulns_proposed)}")
    lines.append(f"- Gate runs: {len(run.gate_results)}")
    lines.append(f"- Decoy attempts: {len(run.decoy_attempts)}")
    lines.append(f"- Cost (est. USD): ${run.cost_usd:.2f}")
    lines.append("")

    # Gate results aggregated by gate name
    gates_outcome: dict[str, dict[str, int]] = {}
    for r in run.gate_results:
        bucket = gates_outcome.setdefault(
            r.gate, {"pass": 0, "fail": 0, "skipped": 0, "error": 0}
        )
        bucket[r.outcome] += 1
    if gates_outcome:
        lines.append("## Gate outcomes")
        lines.append("")
        lines.append("| Gate | pass | fail | skipped | error |")
        lines.append("|---|---:|---:|---:|---:|")
        for name in sorted(gates_outcome):
            b = gates_outcome[name]
            lines.append(
                f"| {name} | {b['pass']} | {b['fail']} | {b['skipped']} | {b['error']} |"
            )
        lines.append("")

    # Per-probe roll-up
    if run.gate_results:
        lines.append("## Per-probe gate roll-up")
        lines.append("")
        lines.append(
            "| Probe | Invariant | Channel | Gates passed | Gates failed | Errors |"
        )
        lines.append("|---|---|---|---:|---:|---:|")
        per_probe: dict[str, dict[str, int]] = {}
        for r in run.gate_results:
            if r.artifact_kind != "probe":
                continue
            d = per_probe.setdefault(
                r.artifact_id, {"pass": 0, "fail": 0, "skipped": 0, "error": 0}
            )
            d[r.outcome] += 1
        probe_index = {p.probe_id: p for p in run.probes_proposed}
        for pid in sorted(per_probe):
            p = probe_index.get(pid)
            row = per_probe[pid]
            lines.append(
                f"| {pid} | "
                f"{p.invariant_id if p else '?'} | "
                f"{p.channel if p else '?'} | "
                f"{row['pass']} | {row['fail']} | {row['error']} |"
            )
        lines.append("")

    # Rejection log
    if run.rejections:
        lines.append("## Rejected artifacts")
        lines.append("")
        for rej in run.rejections:
            lines.append(f"- {rej}")
        lines.append("")

    # Decoy results
    if run.decoy_attempts:
        succeeded = [d for d in run.decoy_attempts if d.succeeded]
        lines.append("## Adversarial decoys")
        lines.append("")
        lines.append(
            f"- Total decoy attempts: {len(run.decoy_attempts)}  |  "
            f"Decoys that fooled a probe: **{len(succeeded)}** "
            f"(non-zero = probe is not robust to that decoy class)"
        )
        if succeeded:
            lines.append("")
            for d in succeeded:
                lines.append(
                    f"- {d.against_artifact}: {d.decoy_class} via {d.model_family} — {d.description}"
                )
        lines.append("")

    return "\n".join(lines)


def _default_json(obj: object) -> object:
    """JSON fallback for dataclasses that haven't gone through to_dict()."""
    try:
        return asdict(obj)  # type: ignore[arg-type]
    except TypeError:
        return str(obj)


# Convenience builder for the no-LLM gate sweep used by tests.
def make_clean_baseline_only_sequence() -> list[tuple[GateName, SetupHook]]:
    """The cheapest gate sequence: just clean_baseline with a no-op setup.

    Useful for verifying that an existing probe set is well-behaved (does
    not fire on a clean app). Used by integration tests.
    """
    return [("clean_baseline", noop_setup)]


__all__ = [
    "make_clean_baseline_only_sequence",
    "make_run_id",
    "render_run_summary_md",
    "run_gate_suite",
]
