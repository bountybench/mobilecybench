# Glossary

This page maps the vocabulary used in the MobileCyBench paper onto the identifiers you will actually type in this repository.

The two differ on purpose. The paper names concepts; the code names fields. Configuration keys, JSON fields, and status values are **deliberately left at their original spellings** — renaming them would invalidate every saved run log and scoring artifact behind the reported results. So when a config asks for `attacker_model` and the paper says *attack setting*, they are the same thing.

## Core terms

| Paper term | In this repo | What it means |
|---|---|---|
| **attack setting** | `attacker_model` (config key) | The privileges and position granted to the attacker. Two exist. |
| **same-device malicious app** | `attacker_model: "malicious_app"` | An unprivileged app installed next to the victim on the same device. The agent submits an `exploit_apk/` directory that the evaluator compiles, installs, and launches. |
| **remote low-privilege attacker** | `attacker_model: "remote_attacker"` | An off-device attacker holding one ordinary, non-administrative account on the application's backend. The agent submits an `exploit.sh` run in a sandboxed container. |
| **access level** | `no_codebase` (+ `apk_obfuscation`) | How much of the target the agent gets. Two levels. |
| **source-visible** | `no_codebase: false` | The agent gets the application's source tree at `/app/codebase` in addition to the APK. |
| **APK-only** | `no_codebase: true`, `apk_obfuscation: "on"` | The agent gets only the shipped obfuscated (R8-minified) release APK and must reverse-engineer it. This is the paper's default condition. |
| **configuration** | one grid cell of a batch sweep | One *agent* on one application, under one attack setting, at one access level. |
| **run** | one `runner.py` invocation / one `logs/<run-id>/` directory | One agent attempt at one configuration. The paper reports pass@2: every configuration is attempted twice, so it has two runs. |
| **triggered** | `triggered` (status value) | At least one probe fired on the replayed exploit. A configuration counts as triggered if *either* of its two runs triggers. |
| **not triggered** | `not_triggered` (status value) | The replay completed and no probe fired. |
| **probe** | `apps/<app>/test_*.py`, `apps/<app>/checks/*.py` | An executable check of one security property against post-replay state. |
| **probe suite** | an app's full probe set | Every probe for one application, plus the generic probes. Written once per application, not once per vulnerability, and hidden from the agent. |
| **security property** | — | A condition on application state that must hold against an attacker with the privileges the attack setting grants. |
| **seeded baseline** | `apps/<app>/seed_baseline.py`, `prepare_victim.py`, `setup.sh` | The emulator plus backend containers, seeded with accounts, files, messages, and settings, that every run and every replay starts from. |
| **exploit** | `exploit_apk/`, `exploit.sh` under `/app/agent_exploit/` | The single replayable artifact an agent submits. |
| **reference vulnerability** / **vulnerability-attribution package** | `apps/<app>/zero_day_vulnerabilities/<name>/` | A pinned vulnerable baseline (`prepare_app.sh`), a reference exploit (`exploit_files/`), a patch that removes the vulnerability (`fix.patch`), and a verifier (`verify_files/`). |
| **attribution** | replay against the vulnerable and patched builds, then diff the probe outcomes | The post-hoc step identifying which vulnerability a triggered exploit reproduced. It never changes a probe score. |
| **candidate finding** | — | A suspected security issue triaged as plausible, not yet confirmed by anyone outside the project. |
| **maintainer-validated** | — | A candidate a maintainer confirmed by patch, acknowledgement, advisory, CVE, or bounty. |
| **coding agent** | `agent_mode: "external"` + `agent_image` | The model-plus-scaffold unit under evaluation. |

Note on grid sizes: the committed sequential batch config excludes `termux`'s remote-attacker setting because it has no backend, giving (13 malicious-app + 12 remote-attacker) × 2 access levels = **50 configurations for one agent**. Across the 5 evaluated agents, the paper reports 250 configurations, each attempted twice. The separate GKE generator still schedules 52 configurations per agent, including the two excluded Termux cells.

## The four property families (CIAA)

Probe suites classify each property into one of four families:

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
| cell | run (one attempt) or configuration (one grid slot), depending on which is meant |
| probe surface | probe suite |
| security expectation, security boundary | security property |
| exploit artifact, saved attack | exploit |
| threat model, attacker scenario | attack setting |
| visibility, access mode | access level |
| agent system, frontier agent | coding agent |
| zero-day bundle, replay package | reference vulnerability / vulnerability-attribution package |

"Finding" is *not* deprecated. The paper uses it for the disclosure record — a candidate finding becomes maintainer-validated — and reserves "vulnerability" for what attribution names behind a trigger.

## A note on "zero-day"

The repo uses `zero_day_vulnerabilities/` and `zero_day_task_bundle_schema.json` as path and schema names. The paper does not count zero-days: a zero-day is standardly a flaw unknown to the vendor, and vendor knowledge is not observable from outside. The criterion the paper counts against is **previously unreported** — absent from the public record at the time we reported it. Read the directory names as historical, not as a claim about vendor awareness.
