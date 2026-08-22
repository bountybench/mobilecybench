# Glossary

This page maps the vocabulary used in the MobileCyBench paper onto the identifiers you will actually type in this repository.

The two differ on purpose. The paper names concepts; the code names fields. Configuration keys, JSON fields, and status values are **deliberately left at their original spellings** — renaming them would invalidate every saved run log and scoring artifact behind the reported results. So when a config asks for `attacker_model` and the paper says *attack setting*, they are the same thing.

## Core terms

| Paper term | In this repo | What it means |
|---|---|---|
| **attack setting** | `attacker_model` (config key) | The privileges and position granted to the attacker. Two exist. |
| **same-device malicious app** | `attacker_model: "malicious_app"` | An unprivileged app sideloaded next to the victim on the same device. The agent submits an `exploit_apk/` directory that the evaluator compiles, installs, and launches. |
| **remote low-privilege attacker** | `attacker_model: "remote_attacker"` | An off-device attacker holding one ordinary, non-administrative account on the application's backend. The agent submits an `exploit.sh` run in a sandboxed container. |
| **source-visible** | `no_codebase: false` | The agent gets the application's source tree at `/app/codebase`. |
| **APK-only** | `no_codebase: true`, `apk_obfuscation: "on"` | The agent gets only the shipped R8-minified release APK and must reverse-engineer it. |
| **run** | one "cell" in batch output | One agent attempt at one task. |
| **configuration** | one row of `batch.matrix` | One application under one attack setting at one level of code access. 13 apps × 2 attack settings × 2 access levels = 52 configurations. |
| **triggered** | `triggered` (status value) | The replayed exploit fired at least one probe. |
| **not triggered** | `not_triggered` (status value) | The replay completed and no probe fired. |
| **probe** | `test_*.py`, `checks/*.py` | An executable check of one security property against post-replay state. |
| **probe suite** | an app's full probe set | Every probe for one application. Written once per application, not once per vulnerability. |
| **security property** | — | A condition on application state that must hold for an attacker with the privileges the attack setting grants. |
| **hydrated baseline** | `seed_baseline.py`, `scripts/hydration/` | The emulator plus backend containers, seeded with realistic data, that a run starts from. |
| **exploit** | `exploit_apk/`, `exploit.sh` | The single replayable artifact an agent submits. |
| **reference vulnerability** | `synthetic_vulnerabilities/vuln_*/` | A saved exploit, upstream fix, patched build, and sometimes a per-vulnerability verifier, used for attribution. |
| **attribution** | replay against patched vs. unpatched | The post-hoc step identifying which vulnerability a triggered run reproduced. It never changes a probe score. |
| **candidate vulnerability** | — | A suspected security issue a researcher triaged as plausible, not yet confirmed. |
| **validated vulnerability** | — | A candidate a maintainer confirmed by patch, acknowledgement, advisory, CVE, or bounty. |
| **coding agent** | `agent_mode: "external"` + `agent_image` | The model-plus-scaffold unit under evaluation. |

## The four property families (CIAA)

Every probe suite covers four families:

- **C**onfidentiality — private data does not become readable by a party that should not read it
- **I**ntegrity — state changes only at the request of a party entitled to change it
- **A**vailability — the application keeps serving its legitimate users
- **A**ccess control — a party does not exceed the authority its role grants

Older docs in this repo say "CIA probes" and name only three. That phrasing is out of date: access control is a fourth family, not a subcase of the others.

## Terms that changed spelling

If you are reading older notes, commits, or issues, these were renamed:

| Older wording | Current wording |
|---|---|
| signal / no_signal | triggered / not_triggered (the code already emits the new spellings; `signal` survives only in saved logs from older runs) |
| cell | run (or configuration, for a grid slot) |
| finding | candidate vulnerability, then vulnerability once validated |
| probe surface | probe suite |
| security expectation, security boundary | security property |
| exploit artifact, saved attack | exploit |
| threat model, attacker scenario | attack setting |
| agent system, frontier agent | coding agent |
| obfuscated | APK-only |
| zero-day bundle, replay package | reference vulnerability |

## A note on "zero-day"

The repo uses `zerodays/` and `zero_day_task_bundle_schema.json` as path and schema names. The paper deliberately avoids the claim: a zero-day is standardly a flaw unknown to the vendor, and vendor knowledge is not observable from outside. The paper's criterion is **previously unreported** — absent from the public record at the time of discovery. Read the directory names as historical, not as a claim about vendor awareness.
