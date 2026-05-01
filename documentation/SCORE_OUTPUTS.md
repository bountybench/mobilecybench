# Probe Score Outputs

`run_checks.sh` emits separate JSON outputs for each probe family:

- **App-specific probes**: `scores.json` by default, or `$APP_SCORES_OUT` when set.
- **Generic probes**: `generic_scores.json` by default, or `$GENERIC_SCORES_OUT` when set.
- **Remote-attacker probes**: `scores_remote_attacker.json` by default when the app has `remote_attacker/` probes and the caller sets `RA_CHECKS_ENABLED=1`, or `$REMOTE_ATTACKER_SCORES_OUT` when set.

`expected_scores.json` is an expected-output fixture for app-specific scenario/gold validation flows. It is not the runtime output of generic probes. Remote-attacker scenario fixtures are optional and use `expected_scores_remote_attacker.json` when present.

Red-team phase artifacts use explicit output paths instead of the default `run_checks.sh` filenames: `probe_app_<phase>.json` for app-specific or attacker-model probe output, and `probe_generic_<phase>.json` for generic probe output when generic probes apply. Remote-attacker red-team tasks do not use generic probe applicability.
