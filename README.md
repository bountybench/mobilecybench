# MobileCyBench

MobileCyBench measures AI agent cybersecurity capabilities. Each experiment
puts a coding agent in a realistic environment — a working Android app and its
backend running in an emulator — and asks it to find and exploit a
vulnerability. Detection is automatic: each app ships CIA
(confidentiality / integrity / availability) probes that fire when the agent
takes an action it shouldn't be able to.

Probes are derived from each app's golden flow. We model what the agent's
account is *legitimately* allowed to do under the app's permissions, then
place probes at the boundary — so any action that crosses it trips a signal.

> Start at [**`documentation/README.md`**](documentation/README.md) for the
> curated app list, the source-vs-`apk_only` ablation, and links to the rest
> of the docs.

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

Or run the whole grid **in parallel on GKE** — the same 52-cell grid, fanned
out across a cluster instead of sequential (setup: [`infra/gke/README.md`](infra/gke/README.md)):

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
checkout and runs the full grid: both `attacker_model` values × both
visibility modes (source vs `apk_only`). `network_mode` and `apk_obfuscation`
are coupled to visibility via `batch.matrix` + `batch.exclude` to match the
paper conditions (source → `permissive` / obfuscation `off`; `apk_only` →
`restricted` / obfuscation `on`), giving 13 apps × 2 × 2 = 52 cells.
`continue_on_failure` means
"record a failed cell and continue"; it does not retry failed cells. For more
detail, see
[`documentation/EXPERIMENTS.md`](documentation/EXPERIMENTS.md#run-a-sequential-batch).

## Documentation

Four docs cover the bench-run path end-to-end. The full index is at
[`documentation/README.md`](documentation/README.md).

- [Documentation index + curated app list + ablation overview](documentation/README.md)
- [Getting Started](documentation/GETTING_STARTED.md) — setup + first run
- [Experiments](documentation/EXPERIMENTS.md) — `runner_config.json` reference, pipeline stages, result schema, status codes, MA permission gate
- [Troubleshooting](documentation/TROUBLESHOOTING.md) — common issues

Reference / maintainer material (adding apps / models, BYO agent contracts, CI
mechanics, command cheatsheets, deep architecture notes) lives in
[`documentation/supplemental/`](documentation/supplemental/) — not needed to run
an experiment. Orthogonal/older workflows (synthetic-vuln, zero-day) are in
[`documentation/archive/`](documentation/archive/).

GKE-specific setup (running at scale): [`infra/gke/README.md`](infra/gke/README.md).
