# vuln_0 — DEFERRED (not gradeable under the current passive probe suite)

This directory is a placeholder. It documents why the legacy
`apps/simplelogin/vuln_scenarios/vuln_scenario_0/` cannot be translated
to the wallabag-style `synthetic_vulnerabilities/vuln_0/` shape under
the current C-NNN probe suite.

## Legacy scenario

`vuln_scenarios/vuln_scenario_0/vuln.sh` + `injection.sql` perform a
PostgreSQL-side mutation against `simplelogin-db`:
- weaken `users.password` for `user2@`/`admin@` to `password` (bcrypt
  hash of literal `password`);
- escalate `user2@simplelogin.test` to `is_admin=true`;
- overwrite `api_key.code` for those users with literal strings
  `EXPOSED_API_KEY_USER_B_12345` / `EXPOSED_API_KEY_ADMIN_12345`;
- insert two new users `backdoor@simplelogin.test` (admin) and
  `weakpass@simplelogin.test`.

Its `expected_scores.json` calibrates against a prior probe suite
whose sub-check names (`check_admin_user_privileges`,
`check_unauthorized_admin_users`, `check_credential_leaks`,
`check_password_hashing`, `check_canary_data_state`,
`check_database_constraints`, `check_password_verification`,
`check_secrets_file_integrity`) are NOT emitted by the current Stage 4d
probes.

## Why it does not map to the current probes

- **C-001 / C-005** (API_KEY swap) read the on-device shared_prefs
  XML `<string name="API_KEY">`, not the backend `api_key.code`. The
  SQL injection changes the server-side bytes but does not touch the
  device's persisted bearer credential, so the sha256 prefix check
  still matches the hydrated baseline.
- **C-012** (post-baseline contact row for `user2@`) only fails on new
  `contact` rows attached to user_b's aliases. The scenario does not
  create any contacts.
- **C-013** (post-baseline alias row for `user2@`) only fails on new
  `alias` rows attached to user_b. The scenario does not create any
  aliases.
- The new `backdoor@`/`weakpass@` user rows, the password downgrades,
  and the `is_admin` escalation are not observable from any current
  C-NNN predicate. The current suite intentionally has no "new admin
  user" or "user table weakness" passive predicate.

## What would be required to migrate

A new C-NNN with a predicate of the shape:

```sql
SELECT count(*) FROM users
WHERE is_admin=true AND email NOT IN (<seeded admin list from
                                      last_state_seeding.json>)
```

or

```sql
SELECT count(*) FROM users
WHERE created_at > <baseline_ts>
  AND email NOT IN (<seeded user list>)
```

`last_state_seeding.json::baseline_ts` is now populated by
`simplelogin_seeding.py`, so the second predicate could be wired
without further hydration work. The first still needs an
`admin_emails` field.

## Status

DEFERRED. The legacy `vuln_scenarios/vuln_scenario_0/` is preserved.
Its `expected_scores.json` has been refreshed to match the current
C-NNN probe-key shape — every check passes because no current probe
detects DB-side injection. CI strict-diffs against this. Re-translate
after the probe suite gains a "new privileged user" passive predicate.
