# MobileCyBench

MobileCyBench measures AI agent cybersecurity capabilities. Each experiment
puts a coding agent in a realistic environment — a working Android app and its
backend running in an emulator — and asks it to find and exploit a
vulnerability, with no target vulnerability named in advance. Scoring is
automatic: each application ships a hidden **probe suite** covering four
security property families — confidentiality, integrity, availability, and
access control (CIAA) — and a run is **triggered** as soon as one probe fires.

Each probe encodes one *security property*: a condition on application state
that must hold for an attacker with the privileges the attack setting grants.
A probe fires when that property is violated, which shows the application has
a vulnerability — not which one. Identifying *which* vulnerability is a
separate, post-hoc attribution step that never changes a probe score.

> Start at [**`documentation/README.md`**](documentation/README.md) for the
> curated app list, the source-visible vs. APK-only ablation, and links to the
> rest of the docs. New to the terminology? See
> [**`documentation/GLOSSARY.md`**](documentation/GLOSSARY.md), which maps the
> paper's terms onto the config keys you actually type.

## Setup

Set up first: [**`documentation/GETTING_STARTED.md`**](documentation/GETTING_STARTED.md)
covers prerequisites, clone + submodules, the Python env, and agent
authentication. The run commands below assume a set-up repo and an authenticated
agent.

## TL;DR run commands

You can run either one app with the normal runner config:

```bash
python runner.py <app> --config runner_config.json
```

Or run the active app set sequentially with a batch config:

```bash
python runner.py --config runner_config_batch.json
```

For **parallel execution on GKE**, see [`infra/gke/README.md`](infra/gke/README.md).
Its separate scheduler currently includes the two Termux remote-attacker cells
excluded from the paper, giving 52 configurations per agent:

```bash
python infra/gke/generate_jobs.py --all \
  --agent-image cybench/mobilecybench:claudecode_2.1.170-r1 \
  --models claude-opus-4-8 --apply
```

`runner.py` is still the only user-facing runner command. `batch_runner.py` is
an internal orchestration module that `runner.py` calls when the config contains
a top-level `batch` block.

`runner_config_batch.json` is the batch equivalent of `runner_config.json`: the
top-level fields are normal runner defaults (`workflow`, `model`,
`agent_image`, token limits, etc.), and the `batch` block selects apps and
matrix fields. By default, `batch.apps: "in_scope"` reads the active app list
from [`apps/app_catalog.json`](apps/app_catalog.json):`sets.in_scope` in this
checkout and runs the full grid: both `attacker_model` values (the paper's two
*attack settings*) × both access levels (source-visible vs. APK-only).
`network_mode` and `apk_obfuscation` are coupled to the access level via
`batch.matrix` + `batch.exclude` to match the paper conditions (source-visible
→ `permissive` / obfuscation `off`; APK-only → `restricted` / obfuscation
`on`). The batch excludes `termux` with `remote_attacker`, because Termux has
no backend, giving (13 malicious-app + 12 remote-attacker) × 2 access levels
= 50 configurations for one agent, matching the paper.
`continue_on_failure` means
"record a failed run and continue"; it does not retry failed runs. For more
detail, see
[`documentation/EXPERIMENTS.md`](documentation/EXPERIMENTS.md#run-a-sequential-batch).

## Documentation

These docs cover the bench-run path end-to-end. The full index is at
[`documentation/README.md`](documentation/README.md).

- [Documentation index + curated app list + ablation overview](documentation/README.md)
- [Getting Started](documentation/GETTING_STARTED.md) — setup + first run
- [Experiments](documentation/EXPERIMENTS.md) — `runner_config.json` reference, pipeline stages, result schema, status codes, malicious-app permission gate
- [Troubleshooting](documentation/TROUBLESHOOTING.md) — common issues
- [Glossary](documentation/GLOSSARY.md) — paper terminology mapped onto repo config keys

Reference / maintainer material (adding apps / models, BYO agent contracts, CI
mechanics, command cheatsheets, deep architecture notes) lives in
[`documentation/supplemental/`](documentation/supplemental/) — not needed to run
an experiment. Orthogonal/older workflows (reference-vulnerability authoring,
targeted task bundles) are in
[`documentation/archive/`](documentation/archive/).

GKE-specific setup (running at scale): [`infra/gke/README.md`](infra/gke/README.md).
