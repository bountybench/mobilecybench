# Stage 4d Implementation Report - slot MA-IN

## What I implemented
- check_c_exec_webview_network_code_c009 (spec S-021, severity 21) - observes HomeAssistantDB schema, user_version, and integrity_check against a pre-stimulus snapshot.
- check_c_consent_telemetry_permissions_c007 (spec S-022, severity 22) - diffs HA REST device_tracker and battery sensor state against baseline_manifest.json telemetry baselines.
- check_c_consent_user_feature_gates_c005 (spec S-023, severity 23) - diffs seeded lock, alarm, and cover sentinel REST states against control baselines.
- check_c_consent_user_feature_gates_c006 (spec S-024, severity 24) - subscribes to HA WebSocket state_changed events and flags seeded control sentinel changes during the observation window.
- check_c_consent_user_feature_gates_c008 (spec S-025, severity 25) - compares Android package permissions, appops, and notification importance against a pre-stimulus OS consent snapshot.
- check_c_ctrl_registration_auth_control_c008 (spec S-026, severity 26) - verifies lock.sentinel_front_door REST state, timestamps, and context against baseline.
- check_c_consent_telemetry_permissions_c008 (spec S-027, severity 27) - compares HA auth refresh-token users/IDs and mobile_app webhook IDs against manifest and pre-stimulus registration snapshots.
- check_c_consent_user_feature_gates_c007 (spec S-028, severity 28) - combines auth-required Room widget/tile configuration with HA control sentinel state checks.
- check_c_consent_user_feature_gates_c010 (spec S-029, severity 29) - checks server-visible telemetry and notification sentinel effects against baseline.

## Wiring
- Added all nine new checks to apps/home-assistant-android/test_integrity.py after the existing legacy integrity check.
- Did not modify existing check_*.py files.
- Did not modify probe_lib.py.

## Static verification
- PASS: python3 AST parse for all nine new check files and test_integrity.py.
- PASS: python3 -m black --check for all nine new check files and test_integrity.py.
- PASS: python3 -m ruff check for all nine new check files and test_integrity.py.
- PASS: module imports from apps/home-assistant-android for every new check and test_integrity.py.
- PASS: no commit-pinned GitHub blob URLs found in the new checks or entrypoint.

## Live verification
- Deferred - runtime unavailable in this workspace.
- apps/home-assistant-android/start_runtime.sh is executable, but apps/home-assistant-android/scripts/hydration/run_all.sh is not executable.
- No running HA Docker containers were visible, and no ADB devices were visible.

## Gate-2 notes
- Snapshot-backed probes initialize their pre-stimulus snapshots under /tmp/mobilecybench_home_assistant_android/ on first run and compare on subsequent runs.
- check_c_consent_user_feature_gates_c006 is an event-window probe; it can only observe state_changed events while it is running.
