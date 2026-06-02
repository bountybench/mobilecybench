# Archived documentation

This folder holds docs that are **not part of the current benchmark flow**.

The benchmark is **redteam probe-only** runs against a curated set of apps
(see [`../README.md`](../README.md)). The docs here describe either:

- **orthogonal workflows** that exist in code but aren't what we measure
  (synthetic-vulnerability runs, two-phase redteam with task bundles,
  zero-day reports, etc.), or
- **maintainer / extender content** that's not needed to run an experiment
  (how to onboard a new app, how to register a new model, deep architecture
  notes, CI mechanics).

They're kept here so links from older PRs / commits don't 404 and so anyone
who explicitly needs them can still find them — but new contributors should
start at [`../README.md`](../README.md), not here.

## Contents

### Orthogonal workflows (not part of probe-only)

| File | Why archived |
|---|---|
| [`SYNTHETIC_VULNERABILITIES.md`](SYNTHETIC_VULNERABILITIES.md) | Synthetic-vuln workflow (`build_type=source --vuln <id>` + verifier). The benchmark has moved to probe-only redteam runs over real apps. |
| [`TASK.md`](TASK.md) | Zero-day task bundle format (`task=<dir>` under `zerodays/reports/<app>/`). Two-phase redteam mode. |
| [`ZERODAY_TASKS.md`](ZERODAY_TASKS.md) | Zero-day onboarding companion to `TASK.md`. |
| [`HTTPS_UPGRADE_GUIDE.md`](HTTPS_UPGRADE_GUIDE.md) | One-time migration guide for the HTTP→HTTPS app-server cutover; complete. |

### Extender / maintainer docs (not needed to run an experiment)

| File | Why archived |
|---|---|
| [`ADDING_APPS.md`](ADDING_APPS.md) | Walkthrough for onboarding a new app into the benchmark. Useful when adding apps; not needed for running. |
| [`ADDING_MODELS.md`](ADDING_MODELS.md) | Registering a model in custom mode or via a BYO image. Useful when adding model coverage. |
| [`BRING_YOUR_OWN_AGENT.md`](BRING_YOUR_OWN_AGENT.md) | Building a new BYO agent CLI image. The reference images (claude-code, codex, opencode) are already pinned in `GETTING_STARTED.md`; this doc is only relevant if you're building a new one. |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Deep system mental model (container topology, network membership, agent capabilities, GKE deployment). |
| [`CI_VALIDATION.md`](CI_VALIDATION.md) | CI modes + `run_ci_local.sh` reference. Maintainer-facing. |
| [`COMMANDS.md`](COMMANDS.md) | Command cheatsheet grouped by workflow. |
| [`UI_AUTOMATION.md`](UI_AUTOMATION.md) | UI-automation tool reference. |

Dated investigation reports and per-campaign write-ups are not stored here;
those belong as PR descriptions, internal docs, or commit messages tied to the
specific work, not in the repository's documentation tree.
