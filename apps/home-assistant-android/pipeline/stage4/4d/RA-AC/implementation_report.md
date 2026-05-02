# Stage 4d Implementation Report - slot RA-AC

## What I implemented
- check_c_ctrl_registration_auth_control_c004 (spec S-031, severity 31) - nonadmin LLAT rejection at /api/config/core/check_config.
- check_c_ctrl_registration_auth_control_c012 (spec S-032, severity 32) - mobile_app config-entry webhook ID diff against expected_mobile_app_webhook_ids.
- check_c_net_selected_server_trust_c001 (spec S-033, severity 33) - attacker endpoint log check for completed HA-shaped impersonation requests.
- check_c_ctrl_registration_auth_control_c005 (spec S-034, severity 34) - curated admin REST endpoint family rejection for nonadminuser.
- check_c_ctrl_registration_auth_control_c007 (spec S-035, severity 35) - WebSocket auth/current_user identity and privilege check for nonadmin LLAT.
- check_c_net_selected_server_trust_c007 (spec S-036, severity 36) - attacker-container DNS/TCP reachability check to home-assistant-server:8123.
- check_c_net_selected_server_trust_c008 (spec S-037, severity 37) - Docker private_net/shared_net membership check.
- check_c_ctrl_registration_auth_control_c002 (spec S-038, severity 38) - auth-store refresh-token user_id and protected-admin token ID diff.
- check_c_ctrl_registration_auth_control_c001 (spec S-039, severity 39) - nonadmin refresh-token grant followed by WebSocket current-user verification.

## Skipped
- Pre-existing RA-AC specs S-040 through S-043 were intentionally skipped per the retrofit addendum.

## Verification
- `python3` AST parse over all nine new check files: passed.
- `ruff check` over all nine new check files plus `remote_attacker/test_access_control.py`: passed after mechanical import cleanup.
- `black --check` over all nine new check files plus `remote_attacker/test_access_control.py`: passed after formatting.
- `rg -n 'blob/[0-9a-f]{7,}/'` over all nine new check files: no matches.
- `python3 -B` import check for every new `checks.<module>`: passed.
- `python3 -B` import check for `remote_attacker.test_access_control` and check-name wiring: passed.
- Live runtime verification: deferred - runtime was not started in this worker turn to avoid disrupting parallel slot workers.

## Gate-2 notes
- c001 mints a temporary nonadmin refresh token through the documented login flow and revokes it in a finally block.
- c033 treats a missing attacker listener log as no completed HTTP request, but treats an unavailable listener container as infrastructure failure.
