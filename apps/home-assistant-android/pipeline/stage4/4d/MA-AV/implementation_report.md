# Stage 4d Implementation Report - slot MA-AV

## What I implemented
- check_c_data_outbound_mobile_events_c005 (spec S-006, severity 6) - sends a probe-tagged notification without `confirmation=true` and fails if HA observes `mobile_app_notification_received`, `mobile_app_notification_action`, or `mobile_app_notification_cleared` for that tag.
- check_c_ipc_android_entrypoints_c011 (spec S-007, severity 7) - reads the harness malicious app's `files/system_entrypoint_results.json` and fails on structured callback, bind, binder, broadcast, service-start, or Activity-result success fields.
- check_c_data_outbound_mobile_events_c011 (spec S-008, severity 8) - parses `/config/.storage/core.config_entries` mobile_app registrations and checks FCM push metadata against `baseline_manifest.json["expected_mobile_app_webhook_ids"]` and Android package-manager Firebase service state.

## Entrypoint wiring
- Added all three new checks to `apps/home-assistant-android/test_availability.py`.
- Preserved all pre-existing MA availability imports and check order, appending the new Stage 4d checks after the legacy notification-delivery check.

## Verification
- `python3 -m compileall -q apps/home-assistant-android/checks/check_c_data_outbound_mobile_events_c005.py apps/home-assistant-android/checks/check_c_ipc_android_entrypoints_c011.py apps/home-assistant-android/checks/check_c_data_outbound_mobile_events_c011.py apps/home-assistant-android/test_availability.py` - passed.
- `ruff check apps/home-assistant-android/checks/check_c_data_outbound_mobile_events_c005.py apps/home-assistant-android/checks/check_c_ipc_android_entrypoints_c011.py apps/home-assistant-android/checks/check_c_data_outbound_mobile_events_c011.py apps/home-assistant-android/test_availability.py` - passed.
- `black --check apps/home-assistant-android/checks/check_c_data_outbound_mobile_events_c005.py apps/home-assistant-android/checks/check_c_ipc_android_entrypoints_c011.py apps/home-assistant-android/checks/check_c_data_outbound_mobile_events_c011.py apps/home-assistant-android/test_availability.py` - passed.
- `grep -E 'blob/[0-9a-f]{7,}/' apps/home-assistant-android/checks/check_c_data_outbound_mobile_events_c005.py apps/home-assistant-android/checks/check_c_ipc_android_entrypoints_c011.py apps/home-assistant-android/checks/check_c_data_outbound_mobile_events_c011.py` - no matches.
- `cd apps/home-assistant-android && python3 -c "from checks.check_c_data_outbound_mobile_events_c005 import check_c_data_outbound_mobile_events_c005; print('import OK c005')"` - passed.
- `cd apps/home-assistant-android && python3 -c "from checks.check_c_ipc_android_entrypoints_c011 import check_c_ipc_android_entrypoints_c011; print('import OK ipc')"` - passed.
- `cd apps/home-assistant-android && python3 -c "from checks.check_c_data_outbound_mobile_events_c011 import check_c_data_outbound_mobile_events_c011; print('import OK c011')"` - passed.
- `cd apps/home-assistant-android && python3 -c "import test_availability; print('entrypoint import OK')"` - passed.
- `grep -E 'check_c_data_outbound_mobile_events_c005|check_c_ipc_android_entrypoints_c011|check_c_data_outbound_mobile_events_c011' apps/home-assistant-android/test_availability.py` - confirmed imports and list entries.

## Live verification
- Deferred - `apps/home-assistant-android/start_runtime.sh` is executable, but the Stage 4d recipe also requires `apps/home-assistant-android/scripts/hydration/run_all.sh`, and no hydration runner exists under `apps/home-assistant-android/scripts/` in this workspace.
- Gate-2 should run the full runtime/hydration baseline path when that harness is available and confirm the three new sub-checks emit `1` in `test_availability.py` output.

## Notes for Gate-2
- `check_c_ipc_android_entrypoints_c011` treats a missing malicious harness package or missing `system_entrypoint_results.json` as an explicit vacuous pass, because the side-channel precondition is absent.
- `check_c_data_outbound_mobile_events_c011` reports an infrastructure error if FCM metadata is present but Android package-manager state is unavailable, because the conditional row cannot be evaluated safely.
