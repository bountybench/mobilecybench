# Supplemental documentation

Detailed reference and maintainer/extender material that the main docs link to
but that you don't need to run an experiment. Start at
[`../README.md`](../README.md) for the run path.

These pages use the repo's literal path and command names (`synthetic_vulnerabilities/`,
`zerodays/`, `attacker_model`, …). [`../GLOSSARY.md`](../GLOSSARY.md) maps those onto the
terminology used in the paper.

## Contents

| File | What it covers |
|---|---|
| [`BRING_YOUR_OWN_AGENT.md`](BRING_YOUR_OWN_AGENT.md) | BYO agent image contract — plug in your own coding-agent CLI. |
| [`ADDING_APPS.md`](ADDING_APPS.md) | Onboard a new app into the benchmark. |
| [`ADDING_MODELS.md`](ADDING_MODELS.md) | Register a model in custom mode or via a BYO image. |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Deep system mental model: container topology, network membership, agent capabilities, GKE deployment. |
| [`CI_VALIDATION.md`](CI_VALIDATION.md) | CI modes + `run_ci_local.sh` reference. |
| [`COMMANDS.md`](COMMANDS.md) | Command cheatsheet grouped by workflow. |
| [`HTTPS_UPGRADE_GUIDE.md`](HTTPS_UPGRADE_GUIDE.md) | HTTP→HTTPS app-server migration guide (referenced when onboarding apps). |
