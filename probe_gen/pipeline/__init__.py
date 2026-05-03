"""Probe-generation pipeline modules.

See ``probe_gen/DESIGN.md`` for the full architecture.

Module layout:

- ``models``         — pure data classes (Invariant, Probe, ProbeRun, GateResult, ...)
- ``archetypes``     — per-archetype defaults (trust boundaries, CWE focus, invariant templates)
- ``threat_model``   — Phase 1.0: bootstrap a threat_model.md from upstream sources
- ``invariants``     — Phase 1.3: derive invariants from threat model + archetype + golden flow
- ``probes``         — Phase 1.4 + 2: synthesize probe (check_*.py) source code
- ``gates``          — Phase 2.5: clean baseline / idle / golden-flow / cross-app / decoy gates
- ``decoys``         — Phase 2.5 sub-component: cross-family adversarial decoy runner
- ``synthesis``      — Phase 2: vulnerability.patch + exploit synthesis
- ``coverage``       — Phase 1.5: CVE coverage audit / matrix generation
- ``runner``         — top-level orchestrator that wires the above together

Modules are introduced in dependency order (``models`` first, ``runner`` last)
so partial implementations remain importable.
"""
