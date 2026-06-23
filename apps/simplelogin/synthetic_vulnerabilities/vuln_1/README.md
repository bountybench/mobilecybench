# vuln_1 — DEFERRED (covered by the generic availability probe)

This directory is a placeholder. It documents why the legacy
`apps/simplelogin/vuln_scenarios/vuln_scenario_1/` is structurally
covered by the **generic availability probe** and does not need an
app-specific `synthetic_vulnerabilities/vuln_1/` translation.

## Legacy scenario

`vuln_scenarios/vuln_scenario_1/vuln.sh` simulates a DDoS by:
- `docker kill simplelogin-api` (kills the backend API container);
- `adb shell am force-stop io.simplelogin.android.fdroid`
  (force-stops the Android app).

## Why it is already covered

The generic availability probe is enabled via
`metadata.json::container_names = ["simplelogin-db", "simplelogin_tls_proxy", "simplelogin-api"]`
and `generic_probe_config.json::availability.check_container_health = true`.
When `simplelogin-api` is killed, the generic probe inspects container
health and emits `score: 0` for the (availability) cell. No app-specific
predicate is required.

The `am force-stop` of the Android app arm is NOT detected by the current
passive C-NNN suite — we do not have a passive `pidof` predicate
(`pidof` after `pm clear` would also be empty in a legitimate restart,
so this would be reward-hackable). For the same reason
`probe_design.md §7 Gap 2` explicitly leaves the
(remote_attacker × availability) cell empty.

## Status

DEFERRED. Container-health arm is covered by the generic probe via
`generic_probe_config.json::availability.check_container_health=true`
and the populated `metadata.json::container_names`. The
`am force-stop` arm intentionally has no passive predicate per
`probe_design.md §7 Gap 2`. The legacy
`vuln_scenarios/vuln_scenario_1/` is preserved; its
`expected_scores.json` has been refreshed to match the current C-NNN
probe keys (every app-specific check passes — detection happens in
the generic availability probe, not in `scores.json::*_details`).
