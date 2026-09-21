# probe_gen

Automated pipeline for generating per-app **invariants** (declarative shall-not statements), **probes** (check functions that test invariants), and **synthetic vulnerabilities** (bugs we introduce to validate that probes fire) for MobileCybench.

One invariant : N probes. One invariant : ≥1 synthetic vulnerability validating it. Each synthetic vulnerability targets one invariant and must trigger ≥1 of its probes.

Output integrates with the existing per-app layout established by recent commits ([`apps/home-assistant-android/`](../apps/home-assistant-android/) is the canonical reference) and powers a new `discovery` workflow alongside the existing `exploit` and `redteam` workflows.

## Status

Pre-implementation. Design phase. See [DESIGN.md](DESIGN.md) for the full plan, rubrics, and phase breakdown.

## Layout

```
probe_gen/
├── DESIGN.md                # Full design doc (rubrics, phases, FP defenses)
├── README.md                # This file
├── ATTRIBUTION.md           # Ported components and licenses (created when first port lands)
├── scripts/                 # CLI entry points (no LLM dependency)
│   ├── profile_probe_run.py      # Phase 0.1: profile a CI run with timestamped phase markers
│   ├── reclassify_log.py         # Re-classify an existing full.log against tuned markers (no re-run)
│   ├── markers.json              # Phase marker regexes for the profiler
│   ├── audit_app_layout.py       # Per-app probe-layout maturity audit (gap matrix)
│   ├── generate_coverage_matrix.py  # Phase 1.5: CVE coverage audit per app
│   ├── scaffold_app_layout.py    # Create the empty modernized layout for an app (dry-run by default)
│   ├── materialize_probe_spec.py # Materialize a probe-spec JSON into apps/<app>/checks/check_*.py
│   ├── app_status.py             # One-shot status report for one app (archetype, modernization, CVE preview)
│   ├── analyze_tier1_savings.py  # Estimate Tier 1 (AVD snapshot) savings from a profile summary
│   ├── run_pipeline.py           # End-to-end CLI: validate → materialize → run gates
│   ├── avd_snapshot.py           # AVD snapshot save/load/list/delete CLI
│   ├── warm_cycle.py             # Bring system to warm state + save snapshot (Phase 0.1 setup)
│   ├── run_discovery.py          # Discovery-mode CLI: walk probes, score, emit report
│   ├── derive_invariants.py      # LLM-driven invariant derivation: archetype + metadata → invariants.json
│   ├── synthesize_probes.py      # LLM-driven probe-body synthesis: invariants.json → probe spec + check_*.py
│   ├── derive_probe_lib.py       # LLM-driven per-app probe_lib.py generation (grounded in docker-compose / metadata)
│   ├── synthesize_patch.py       # LLM-driven vulnerability.patch synthesis (with hunk-header recount + git apply check)
│   ├── synthesize_exploit.py     # LLM-driven exploit.sh + exploit.py synthesis (remote_attacker model)
│   └── generate_decoys.py        # LLM-driven adversarial-decoy generation (Phase 2.5 FP gate)
├── shared_helpers.py        # Phase 0.2: cross-app probe primitives extracted from real probe_libs
├── pipeline/                # Pipeline modules
│   ├── models.py                 # Invariant / Probe / SyntheticVulnerability / GateResult / ProbeGenRun
│   ├── archetypes.py             # Per-archetype defaults + invariant templates (30 apps tagged)
│   ├── probes.py                 # check_*.py source-code scaffolder + anti-pattern catalogue
│   ├── prompts.py                # LLM prompt templates (5 phases, validated against required_inputs)
│   ├── gates.py                  # GateRunner + ProbeRunOutcome + setup-hook abstraction
│   ├── runner.py                 # Top-level: run_gate_suite, render_run_summary_md
│   ├── coverage.py               # CVE → invariant coverage matrix builder
│   ├── validation.py             # Static rubric validation: invariants, probes, synthetic vulns, full spec
│   ├── snapshots.py              # AVD snapshot save/load + setup-hook factory (Phase 0.1 Tier 1)
│   ├── discovery.py              # Discovery-mode evaluator: probe walk + severity-weighted scoring
│   ├── threat_model.py           # Parser for threat_model.md → ParsedShallNot / Invariant
│   ├── llm.py                    # Stateless LLM client: complete / complete_json / cross_family_pick (litellm-backed)
│   └── decoys.py                 # Adversarial decoy generator (Phase 2.5 cross-family verifier-trust gate)
├── runs/                    # Per-run output: verbose logs, summaries, audits, scaffold previews
└── tests/                   # Pipeline unit tests (stdlib unittest)
```

Generated artifacts land in the existing per-app layout under `apps/<app>/`, not under `probe_gen/`. See [DESIGN.md §Artifact layout](DESIGN.md#artifact-layout).

## What's runnable today

```bash
# Profile one synthetic-vuln CI run end-to-end (Phase 0.1 — needs emulator+Docker)
python probe_gen/scripts/profile_probe_run.py --app conversations --vuln vuln_0

# Re-classify an existing log against tuned markers (no re-run needed)
python probe_gen/scripts/reclassify_log.py --log probe_gen/runs/<id>/full.log

# Audit modernization gap across all 30 apps
python probe_gen/scripts/audit_app_layout.py

# CVE coverage matrix for one app (no invariants yet → all gaps)
python probe_gen/scripts/generate_coverage_matrix.py --app conversations

# Scaffold the empty modernized layout for one app (dry-run)
python probe_gen/scripts/scaffold_app_layout.py --app conversations
# Or write to a sandbox for review:
python probe_gen/scripts/scaffold_app_layout.py --app conversations --preview-dir probe_gen/runs/scaffold_preview

# Materialize a probe-spec JSON into apps/<app>/checks/ (dry-run by default)
python probe_gen/scripts/materialize_probe_spec.py --spec <spec.json>
python probe_gen/scripts/materialize_probe_spec.py --spec <spec.json> --apply

# One-shot app status report (modernization + CVE coverage preview)
python probe_gen/scripts/app_status.py --app conversations

# Phase 0.1 Tier 1 — bring the runtime to warm state and snapshot it
JAVA_HOME='/c/Program Files/Java/jdk-17' ANDROID_HOME=$HOME/.android-sdk \
    python probe_gen/scripts/warm_cycle.py --app conversations --snapshot warm-conversations

# Then per-iteration: load the snapshot in ~10s instead of warming up in ~7m
python probe_gen/scripts/avd_snapshot.py load --name warm-conversations

# Discovery-mode evaluation (Phase 4.5 evaluator core — runs all probes + scores)
python probe_gen/scripts/run_discovery.py --app home-assistant-android

# Run the test suite (109 tests, stdlib only)
python -m unittest discover probe_gen/tests
```

## Reading order

1. [DESIGN.md](DESIGN.md) — architecture, phases, rubrics
2. [`apps/home-assistant-android/threat_model.md`](../apps/home-assistant-android/threat_model.md) — canonical per-app threat model with shall-nots (= invariants)
3. [`apps/home-assistant-android/checks/check_no_new_admin_refresh_tokens.py`](../apps/home-assistant-android/checks/check_no_new_admin_refresh_tokens.py) — canonical probe shape (anti-pattern declarations, baseline diff, channel naming)
4. [`apps/home-assistant-android/probe_config_rationale.md`](../apps/home-assistant-android/probe_config_rationale.md) — per-probe FP risk / FN risk / cheapest-known-cheat documentation
5. [`apps/home-assistant-android/synthetic_vulnerabilities/vuln_0/`](../apps/home-assistant-android/synthetic_vulnerabilities/vuln_0/) — synthetic-vulnerability example (target output shape for Phase 2)
6. [documentation/SYNTHETIC_VULNERABILITIES.md](../documentation/SYNTHETIC_VULNERABILITIES.md) — existing synthetic-vuln contract
7. [documentation/ARCHITECTURE.md](../documentation/ARCHITECTURE.md) — runtime context

## Vendoring policy

The pipeline ports code and patterns from published open-source work where licenses allow. Every ported file:

- Carries a header comment naming its origin (paper, repo URL, commit hash)
- Is listed in `ATTRIBUTION.md` with rationale and license reference
- Documents which parts are unmodified vs. adapted

Sources currently planned for vendoring (verify licenses before pulling):

| Source | What we port |
|---|---|
| [CVE-GENIE](https://arxiv.org/abs/2509.01835) ([repo](https://github.com/uiuc-kang-lab/cve-bench)) | Multi-agent module structure, environment-reconstruction patterns, prompt templates |
| [SEC-bench](https://arxiv.org/abs/2506.11791) | Harness-construction patterns, gold-patch generation |
| [R2E-Gym](https://arxiv.org/abs/2504.07164) | Hybrid verifier patterns (execution-based + execution-free) |

Pull-from-scratch is preferred where the upstream license is incompatible or where the Android harness's runtime is too divergent from the source's assumptions.

## Quickstart (when implementation lands)

To be filled in once the pipeline ships. For now, see [DESIGN.md §Timeline](DESIGN.md#timeline) for the rollout plan.

## Open questions

Tracked in [DESIGN.md §Open questions / decisions deferred](DESIGN.md#open-questions--decisions-deferred). Updates land via PR on this README and DESIGN.md, not in a separate changelog.
