"""Gate orchestration: false-positive defenses + dual-comparator + decoys.

A gate is a one-shot evaluation of one or more probes against a specified
app state, returning ``GateResult.outcome ∈ {pass, fail, skipped, error}``.

This module is the *runner abstraction*. The actual app-state setup
(emulator boot, docker-compose up, victim login, golden-flow scripts) is
delegated to per-gate setup hooks that the pipeline runner installs. That
lets unit tests use a no-op setup hook while the real pipeline wires in
the existing repo machinery (``run_ci_local.sh`` for dual-comparator,
``start_runtime.sh`` for clean-baseline, etc.).

Single-process, sequential — gates do not run concurrently against the
shared emulator. Caller is responsible for cleanup between gates.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Protocol

from probe_gen.pipeline.models import GateName, GateOutcome, GateResult, Probe

# ----- Context -----


@dataclass
class GateContext:
    """Static configuration passed to every gate.

    Mutable state (the emulator, docker, the agent) lives behind setup
    hooks. ``GateContext`` is a value type passed by reference.
    """

    repo_root: Path
    app_dir: Path  # apps/<app>/
    run_dir: Path  # probe_gen/runs/<run_id>/
    env: dict[str, str] = field(default_factory=dict)


# ----- Probe execution -----


@dataclass
class ProbeRunOutcome:
    """Raw subprocess outcome of running a single probe."""

    probe_id: str
    return_code: int
    score: Optional[int]  # parsed from stdout JSON ``{"score": 0|1}``; None if absent
    stdout: str
    stderr: str
    duration_seconds: float

    @property
    def fired(self) -> bool:
        """Did the probe report a violation?

        Convention: probes return ``score: 1`` if the invariant holds (no
        violation), ``score: 0`` if violated. Mirrors HA's
        ``test_*.py`` aggregators. Probes that crash (``rc != 0`` or
        unparseable output) are treated as ``fired = False``; the
        ``error`` GateOutcome path is used for those instead.
        """
        return self.score == 0


def run_probe(probe: Probe, ctx: GateContext, *, timeout: int = 120) -> ProbeRunOutcome:
    """Invoke ``checks/<probe_id>.py`` (or ``remote_attacker/checks/...``).

    Resolves the path from ``probe.source_path`` if set, otherwise infers
    from ``probe.attacker_model``: malicious_app → ``checks/<id>.py``,
    remote_attacker → ``remote_attacker/checks/<id>.py``.
    """
    if probe.source_path:
        script = Path(probe.source_path)
    else:
        if probe.attacker_model == "malicious_app":
            script = ctx.app_dir / "checks" / f"{probe.probe_id}.py"
        else:
            script = ctx.app_dir / "remote_attacker" / "checks" / f"{probe.probe_id}.py"

    if not script.is_file():
        return ProbeRunOutcome(
            probe_id=probe.probe_id,
            return_code=-1,
            score=None,
            stdout="",
            stderr=f"probe source not found: {script}",
            duration_seconds=0.0,
        )

    cmd = ["python", str(script)]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ctx.app_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**ctx.env},
        )
    except subprocess.TimeoutExpired as exc:
        return ProbeRunOutcome(
            probe_id=probe.probe_id,
            return_code=-1,
            score=None,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + f"\n[gate] probe timed out after {timeout}s",
            duration_seconds=time.monotonic() - t0,
        )
    duration = time.monotonic() - t0

    score = _parse_score(proc.stdout)
    return ProbeRunOutcome(
        probe_id=probe.probe_id,
        return_code=proc.returncode,
        score=score,
        stdout=proc.stdout,
        stderr=proc.stderr,
        duration_seconds=duration,
    )


def _parse_score(stdout: str) -> Optional[int]:
    """Pull the last JSON object's ``score`` field out of stdout.

    Probes (and aggregators) emit a final ``json.dumps(...)`` line. We
    walk lines bottom-up to tolerate noisy preludes.
    """
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        score = data.get("score")
        if isinstance(score, int):
            return score
    return None


# ----- Setup hooks: app-state preparation per gate -----


SetupHook = Callable[[GateContext], None]
"""Side-effecting callable that brings the runtime to a state appropriate for a gate.

Hooks raise on setup failure; the gate runner converts that to
``GateOutcome.error``. Hooks should be idempotent where feasible so
mid-run retries are safe.
"""


def noop_setup(ctx: GateContext) -> None:  # pragma: no cover - trivially correct
    """Default hook: do nothing. Used in unit tests."""
    return


# ----- Gate runner -----


class GateRunner(Protocol):
    def run(
        self,
        gate: GateName,
        probes: Iterable[Probe],
        ctx: GateContext,
        *,
        setup: SetupHook = noop_setup,
    ) -> list[GateResult]: ...


class StandardGateRunner:
    """Reference gate runner.

    Per-gate semantics:

    | Gate                       | Expected probe outcome (per probe) |
    |----------------------------|------------------------------------|
    | clean_baseline             | not fired (score == 1)             |
    | idle_with_victim           | not fired                          |
    | golden_flow                | not fired                          |
    | cross_app_baseline         | not fired                          |
    | dual_comparator_clean      | not fired                          |
    | dual_comparator_vulnerable | fired (score == 0) for ≥1 probe    |
    | adversarial_decoy          | not fired                          |

    All gates are ``pass`` if every probe meets expectation; ``fail``
    otherwise. Probe crashes → ``error``.
    """

    GATES_EXPECT_NOT_FIRED = (
        "clean_baseline",
        "idle_with_victim",
        "golden_flow",
        "cross_app_baseline",
        "dual_comparator_clean",
        "adversarial_decoy",
    )

    def run(
        self,
        gate: GateName,
        probes: Iterable[Probe],
        ctx: GateContext,
        *,
        setup: SetupHook = noop_setup,
    ) -> list[GateResult]:
        probes_list = list(probes)
        results: list[GateResult] = []

        t_setup_start = time.monotonic()
        try:
            setup(ctx)
        except Exception as exc:
            for probe in probes_list:
                results.append(
                    GateResult(
                        gate=gate,
                        outcome="error",
                        duration_seconds=time.monotonic() - t_setup_start,
                        artifact_id=probe.probe_id,
                        artifact_kind="probe",
                        detail=f"setup failed: {type(exc).__name__}: {exc}",
                    )
                )
            return results

        outcomes = [run_probe(probe, ctx) for probe in probes_list]

        if gate == "dual_comparator_vulnerable":
            # Aggregate semantics: ≥1 probe must have fired (across all probes
            # for the targeted invariant). One GateResult per probe so we keep
            # per-probe attribution, but the "pass" outcome is decided at the
            # set level.
            any_fired = any(o.fired for o in outcomes)
            for probe, outcome in zip(probes_list, outcomes):
                if outcome.return_code == -1:
                    res_outcome: GateOutcome = "error"
                elif any_fired:
                    res_outcome = "pass" if outcome.fired else "skipped"
                else:
                    res_outcome = "fail"
                results.append(
                    GateResult(
                        gate=gate,
                        outcome=res_outcome,
                        duration_seconds=outcome.duration_seconds,
                        artifact_id=probe.probe_id,
                        artifact_kind="probe",
                        detail=_summarize_outcome(outcome),
                    )
                )
            return results

        # Per-probe semantics for all "expect not fired" gates.
        if gate in self.GATES_EXPECT_NOT_FIRED:
            for probe, outcome in zip(probes_list, outcomes):
                if outcome.return_code == -1 or outcome.score is None:
                    res_outcome = "error"
                elif outcome.fired:
                    res_outcome = "fail"
                else:
                    res_outcome = "pass"
                results.append(
                    GateResult(
                        gate=gate,
                        outcome=res_outcome,
                        duration_seconds=outcome.duration_seconds,
                        artifact_id=probe.probe_id,
                        artifact_kind="probe",
                        detail=_summarize_outcome(outcome),
                    )
                )
            return results

        # Unknown gate — treat as error so it surfaces in the run summary.
        for probe, outcome in zip(probes_list, outcomes):
            results.append(
                GateResult(
                    gate=gate,
                    outcome="error",
                    duration_seconds=outcome.duration_seconds,
                    artifact_id=probe.probe_id,
                    artifact_kind="probe",
                    detail=f"unknown gate: {gate!r}",
                )
            )
        return results


def _summarize_outcome(outcome: ProbeRunOutcome) -> str:
    if outcome.return_code == -1:
        return f"infra error: {outcome.stderr.strip()[:200]}"
    if outcome.score is None:
        return f"unparseable score (rc={outcome.return_code})"
    fired_word = "fired" if outcome.fired else "did not fire"
    return f"score={outcome.score} ({fired_word}) in {outcome.duration_seconds:.2f}s"


# ----- Convenience factory -----


def build_dual_comparator_runner_via_ci_script(
    *, repo_root: Path, app_name: str, vuln_id: str
) -> SetupHook:
    """Returns a setup hook that drives ``run_ci_local.sh --test-synthetic-vuln``.

    Used by Phase 2.4: the existing CI script handles the full
    build/install/exploit flow. The hook simply invokes it; the gate
    runner then runs the probe set against the resulting state to
    determine pass/fail.

    Note: this is an example; the real Phase 2 orchestration may want
    to skip the CI script's verifier step and call probes directly to
    keep gating logic centralized.
    """
    import shutil

    bash = shutil.which("bash") or "bash"

    def hook(ctx: GateContext) -> None:
        cmd = [
            bash,
            "run_ci_local.sh",
            f"apps/{app_name}",
            "--test-synthetic-vuln",
            vuln_id,
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"run_ci_local.sh failed (rc={proc.returncode}): "
                f"{proc.stderr.strip()[:500]}"
            )

    return hook


__all__ = [
    "GateContext",
    "GateResult",
    "GateRunner",
    "ProbeRunOutcome",
    "SetupHook",
    "StandardGateRunner",
    "build_dual_comparator_runner_via_ci_script",
    "noop_setup",
    "run_probe",
]


# Re-export for type-checker friendliness
_ = (shlex,)  # silence unused-import warning if added later
