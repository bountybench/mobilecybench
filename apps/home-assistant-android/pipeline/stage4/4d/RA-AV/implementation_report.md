# Stage 4d Implementation Report - slot RA-AV

## What I implemented
- check_c_consent_user_feature_gates_c001 (spec S-044, severity 44) - observes HA Core WebSocket mobile_app notification events while Android notification delivery is denied, correlated with the seed notification sentinel.
- check_c_consent_user_feature_gates_c002 (spec S-045, severity 45) - observes Android notification-manager active/enqueued records while app notification permission or seeded channels are denied/disabled.
- check_c_net_selected_server_trust_c009 (spec S-046, severity 46) - verifies REST /api/states accepts the baseline LLAT and rejects missing/invalid Bearer credentials.
- check_c_net_selected_server_trust_c010 (spec S-047, severity 47) - verifies WebSocket /api/websocket accepts the baseline LLAT and rejects an invalid access token using structured auth frames.
- check_c_net_selected_server_trust_c011 (spec S-048, severity 48) - verifies mobile_app registration rejects missing/invalid Bearer credentials and accepts the baseline LLAT, then restores the pre-probe config-entry snapshot to remove the probe registration.

## Files changed
- apps/home-assistant-android/checks/check_c_consent_user_feature_gates_c001.py
- apps/home-assistant-android/checks/check_c_consent_user_feature_gates_c002.py
- apps/home-assistant-android/checks/check_c_net_selected_server_trust_c009.py
- apps/home-assistant-android/checks/check_c_net_selected_server_trust_c010.py
- apps/home-assistant-android/checks/check_c_net_selected_server_trust_c011.py
- apps/home-assistant-android/remote_attacker/test_availability.py
- apps/home-assistant-android/probe_lib.py - additive websocket_auth_result helper only for structured invalid-token WebSocket auth checks.

## Verification
- python3 -m py_compile on probe_lib.py, remote_attacker/test_availability.py, and all five new check files: pass.
- ruff check on probe_lib.py, remote_attacker/test_availability.py, and all five new check files: pass.
- black --check on probe_lib.py, remote_attacker/test_availability.py, and all five new check files: pass.
- rg 'blob/[0-9a-f]{7,}/' across all five new check files: no matches.
- Per-check import smoke tests from apps/home-assistant-android for all five new check modules: pass.
- remote_attacker.test_availability entrypoint smoke import for all five new function symbols: pass.
- git diff --check across touched RA-AV files: pass.

## Live verification
- Deferred - runtime baseline is unavailable in this workspace: apps/home-assistant-android/baseline_manifest.json is absent.
- Deferred - I did not run cleanup.sh/start_runtime.sh because other Stage 4d workers are editing/running in parallel and cleanup would be disruptive to shared state.

## Notes for Gate-2
- check_c_consent_user_feature_gates_c001 and c002 intentionally report a named vacuous pass when Android notification delivery is not denied; their violation condition only applies while permission/channel consent is disabled.
- check_c_net_selected_server_trust_c011 sends one legitimate probe-owned mobile_app registration during the valid Bearer branch, matching the Stage 4c implementer note for S-048, and fails with an infrastructure error if the pre-probe `/config/.storage/core.config_entries` snapshot cannot be restored afterward.
