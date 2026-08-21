# Archived documentation

Docs for **orthogonal workflows** that exist in code but aren't what the current
benchmark measures (synthetic-vulnerability runs, two-phase redteam with task
bundles, zero-day reports), plus a couple of one-off references.

The benchmark is **redteam probe-only** runs against a curated set of apps — see
[`../README.md`](../README.md). Current reference / maintainer material lives in
[`../supplemental/`](../supplemental/), not here.

Kept so links from older PRs / commits don't 404 and anyone who explicitly needs
them can still find them.

## Contents

| File | Why archived |
|---|---|
| [`SYNTHETIC_VULNERABILITIES.md`](SYNTHETIC_VULNERABILITIES.md) | Synthetic-vuln workflow (`build_type=source --vuln <id>` + verifier). The benchmark has moved to probe-only redteam runs over real apps. |
| [`TASK.md`](TASK.md) | Zero-day task bundle format under `apps/<app>/zero_day_vulnerabilities/<task_id>/`. Two-phase redteam mode. |
| [`ZERODAY_TASKS.md`](ZERODAY_TASKS.md) | Zero-day onboarding companion to `TASK.md`. |
| [`UI_AUTOMATION.md`](UI_AUTOMATION.md) | UI-automation tool reference. |

Dated investigation reports and per-campaign write-ups are not stored here;
those belong as PR descriptions, internal docs, or commit messages tied to the
specific work, not in the repository's documentation tree.
