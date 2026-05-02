# Stage 4d Implementation Report - slot MA-AC

## What I implemented
- check_c_ffi_native_bridge_c001 (spec S-001, severity 1) - reads the harness malicious-app `native_bridge_results.json` artifact and fails on successful externalApp bridge results or functional captured HA access tokens.
- check_c_exec_webview_network_code_c003 (spec S-002, severity 2) - reads the attacker endpoint JSON log and fails only when a captured bearer/access token authenticates to HA `/api/states`.
- check_c_exec_webview_network_code_c004 (spec S-003, severity 3) - reads Home Assistant Android `HomeAssistantDB` through `adb run-as` and compares persisted server URLs and webhook IDs to `baseline_manifest.json`.
- check_c_ipc_android_entrypoints_c004 (spec S-004, severity 4) - reads the harness malicious-app `protected_service_bind_results.json` artifact and fails on binder delivery for protected service attempts.
- check_c_ipc_android_entrypoints_c005 (spec S-005, severity 5) - reads Android ActivityManager service state and fails if the malicious app remains connected to protected Home Assistant Android service blocks.
- Wired all five checks into `apps/home-assistant-android/test_access_control.py` while preserving the previous `ma_x_deferred` status as a passing diagnostic check.

## probe_lib extensions
- None.

## Static check results
- `python3 -c "import ast, pathlib; ..."` over all five new checks plus `test_access_control.py`: passed (`ast OK`).
- `ruff check` over all five new checks plus `test_access_control.py`: passed.
- `black --check` over all five new checks plus `test_access_control.py`: passed.
- `rg -n 'blob/[0-9a-f]{7,}/|import requests|import httpx|import aiohttp'` over all five new checks: no matches.
- Per-check import checks from `apps/home-assistant-android`: all five printed `import OK`.
- Entrypoint wiring check printed all expected check function names in `test_access_control.CHECKS`.

## Live verification
- Status: deferred - runtime unavailable in this workspace.
- `apps/home-assistant-android/start_runtime.sh` and `cleanup.sh` exist, but `apps/home-assistant-android/scripts/hydration/run_all.sh` is absent.
- Standalone runs were import-safe and exited 0. ADB-backed checks reported `infra error: no adb device available`; the listener-log check passed vacuously because the listener container/log was absent.
- `python3 apps/home-assistant-android/test_access_control.py` exited 0 and emitted JSON with `score: 0` because no ADB device was available for four checks.

## Skipped / blocked
- No specs skipped.
- Baseline live run skipped because the hydration script path is missing and no ADB device is attached.

## Flags for Gate-2 reviewer
- check_c_ffi_native_bridge_c001 and check_c_exec_webview_network_code_c003 use the anti-pattern #3 carve-out to verify captured credentials against HA; confirm the captured artifact is produced by the intended harness in live runs.
- check_c_ipc_android_entrypoints_c005 relies on Android `dumpsys activity services` block structure for ActivityManager service state because there is no JSON API for this runtime channel.

## Open questions
- The Stage 4c specs refer to harness-owned malicious-app result files that are not present in the current checked-in synthetic exploit APK. Gate-2 should confirm the live harness writes `files/native_bridge_results.json` and `files/protected_service_bind_results.json` for these checks.
