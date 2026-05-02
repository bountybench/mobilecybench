# Stage 4d Implementation Report - slot MA-CO

## What I implemented
- check_c_data_outbound_mobile_events_c006 (spec S-010, severity 10) - verifies malicious-helper outbound intent captures do not contain a functional HA access token.
- check_c_ipc_android_entrypoints_c009 (spec S-011, severity 11) - verifies OAuth IPC captures do not contain exchangeable callback codes or functional HA tokens.
- check_c_ipc_android_entrypoints_c001 (spec S-012, severity 12) - checks generic exported-entrypoint results for functional credentials, FileProvider URIs, and app-private storage indicators.
- check_c_ipc_android_entrypoints_c006 (spec S-013, severity 13) - checks ungranted FileProvider open results for copied bytes, including seeded-file SHA-256 confirmation.
- check_c_persist_client_private_state_c001 (spec S-014, severity 14) - checks malicious-UID Room database read results and live-verifies any exposed credentials.
- check_c_persist_client_private_state_c004 (spec S-015, severity 15) - checks malicious-UID SharedPreferences read results with XML parsing and credential verification.
- check_c_persist_files_cert_server_state_c001 (spec S-016, severity 16) - checks downloaded/shared file and FileProvider read results, allowing public Downloads reads only when the structured result records that condition.
- check_c_ipc_android_entrypoints_c002 (spec S-017, severity 17) - diffs HA REST `/api/states` against baseline_manifest.json sentinel entity fields.
- check_c_ipc_android_entrypoints_c003 (spec S-018, severity 18) - parses Android package-manager URI grant state for broad or durable HA FileProvider grants to the malicious package.
- check_c_persist_files_cert_server_state_c003 (spec S-019, severity 19) - combines URI grant-table parsing with malicious-helper URI read results to catch broad grants or grantless FileProvider byte copies.

## Wiring
- Added all ten new checks to `apps/home-assistant-android/test_confidentiality.py`.
- Preserved the pre-existing `check_no_credential_leak_indicators` import, log-path argument, and aggregate behavior.
- Added shared helpers to `apps/home-assistant-android/probe_lib.py` for malicious-helper artifact reads, JSON/JSONL parsing, credential extraction and live verification, FileProvider grant parsing, read-result parsing, SharedPreferences XML parsing, seeded-file hashing, and HA state baseline comparison.

## Verification
- `python3 -m py_compile apps/home-assistant-android/probe_lib.py apps/home-assistant-android/test_confidentiality.py <10 new check files>` - passed.
- `ruff check apps/home-assistant-android/probe_lib.py apps/home-assistant-android/test_confidentiality.py <10 new check files>` - passed.
- `black --check apps/home-assistant-android/probe_lib.py apps/home-assistant-android/test_confidentiality.py <10 new check files>` - passed.
- `cd apps/home-assistant-android && python3 -c '... import all 10 checks and test_confidentiality ...'` - passed (`import OK`).
- `rg 'blob/[0-9a-f]{7,}/' <10 new check files>` - no matches.

## Live verification
- Deferred. `apps/home-assistant-android/start_runtime.sh` is executable, but the required hydration runner `apps/home-assistant-android/scripts/hydration/run_all.sh` is missing or not executable in this workspace, so I did not run cleanup/start/hydration or the full live baseline `python3 test_confidentiality.py`.

## Notes for Gate-2
- The malicious helper package defaults to `com.mobilecybench.exploit`, matching `templates/malicious_app/AndroidManifest.xml`. Gate-2 can override it with `HA_MALICIOUS_PACKAGE` if the live harness uses a different package.
- Checks that depend on malicious-helper result artifacts treat a missing or empty artifact as an explicit vacuous pass. Malformed artifacts are infrastructure failures.
