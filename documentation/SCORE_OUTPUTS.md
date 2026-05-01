# Probe Score Outputs

`run_checks.sh` emits separate JSON outputs for each probe family:

- **App-specific probes**: `scores.json` by default, or `$APP_SCORES_OUT` when set.
- **Generic probes**: `generic_scores.json` by default, or `$GENERIC_SCORES_OUT` when set.
- **Remote-attacker probes**: `scores_remote_attacker.json` by default when the app has `remote_attacker/` probes and the caller sets `RA_CHECKS_ENABLED=1`, or `$REMOTE_ATTACKER_SCORES_OUT` when set.

## Relationship to expected-score fixtures

`expected_scores.json` is not emitted by `run_checks.sh`. It is a checked-in fixture used by the legacy `vuln_scenarios/` CI path to compare against app-specific `scores.json`.

`generic_scores.json` has no standard `vuln_scenarios/` expected-score fixture today. Do not treat `expected_scores.json` as generic probe expectations.

`expected_scores_remote_attacker.json` follows the same fixture pattern for remote-attacker scenario checks, but it is optional and only used when present.

Red-team gold runs are separate from those `vuln_scenarios/` fixtures: they write `apps/<app>/redteam_scores.json` and `logs/gold/experiment_<uuid>_gold/gold_run_result.json`.

## Red-team phase artifacts

Red-team phase artifacts use explicit output paths instead of the default `run_checks.sh` filenames: `probe_app_<phase>.json` for app-specific or attacker-model probe output, and `probe_generic_<phase>.json` for generic probe output when generic probes apply. Remote-attacker red-team tasks do not use generic probe applicability.
