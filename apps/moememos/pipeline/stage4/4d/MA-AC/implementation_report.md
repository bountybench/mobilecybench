# Stage 4d Implementation Report - slot MA-AC

## What I implemented
- check_malicious_app_fileprovider_grant_is_exact_uri_only (spec S-022, severity 22) - grants one hydrated Moe Memos FileProvider fixture URI to the malicious app, verifies exact bytes by SHA-256, and checks sibling URIs remain unreadable.
- check_malicious_app_cannot_browse_fileprovider_without_grant (spec S-023, severity 23) - runs malicious_app ContentResolver reads against hydrated FileProvider and crafted token-path URI candidates before any grant exists.
- check_malicious_app_entrypoints_match_declared_routes (spec S-024, severity 24) - verifies launcher/share resolver exposure and live MainActivity/share route delivery through the hydrated malicious-app launch, text-share, and image-share actions.
- check_declared_shortcut_intents_launch_only_expected_routes (spec S-029, severity 29) - reads Android shortcut metadata and launches only parsed ACTION_VIEW shortcut data URIs when Android exposes them.

## probe_lib extensions
- None. Existing `run_command`, `load_json_state`, and `load_share_payloads` were sufficient.

## Static check results
- `python3 -m py_compile apps/moememos/test_access_control.py apps/moememos/checks/check_malicious_app_fileprovider_grant_is_exact_uri_only.py apps/moememos/checks/check_malicious_app_cannot_browse_fileprovider_without_grant.py apps/moememos/checks/check_malicious_app_entrypoints_match_declared_routes.py apps/moememos/checks/check_declared_shortcut_intents_launch_only_expected_routes.py` - passed.
- AST parse for all four check modules and `test_access_control.py` - passed.
- `ruff check ...` - passed.
- `black --check ...` - passed after formatting.
- Import check from `apps/moememos` for all four check functions plus `test_access_control` - passed.
- No commit-pinned URLs or new HTTP client dependencies found by grep.
- Standalone execution of each module returned JSON and exited 0; because hydration state is absent locally, each reported an expected infra error.

## Live verification
- Status: deferred - runtime unavailable.
- `apps/moememos/pipeline/stage3/run.json` is absent in this worktree, so hydration state has not been generated.
- `adb get-state` with sandbox escalation returned `error: no devices/emulators found`.
- Baseline run output without hydration was `{"score": 0, ...}` with infra errors for missing `malicious_app_storage.json`, `malicious_app.json`, and `android_account.json`; this was not a live baseline verification.

## Skipped / blocked
- None of the assigned specs were skipped.

## Flags for Gate-2 reviewer
- S-022 compares granted bytes against `malicious_app_storage.json:fileprovider_fixtures[*].sha256` rather than `resources.json`, because Stage 3 hydrates deterministic app-private FileProvider fixtures for the malicious-app URI checks.
- S-022 uses an Android framework exact-URI grant for the hydrated Moe Memos FileProvider URI rather than a full Moe Memos external-viewer UI tap. It verifies the exact-grant versus sibling-denial boundary; Gate-2 should require a future UI trigger if source-package provenance must be covered in this probe.
- S-024 now uses the malicious app for launcher, text/plain share, and image/* share delivery. The image stream URI comes from `malicious_app_storage.json` because the generated helper APK does not expose its own FileProvider.
- S-029 intentionally returns a vacuous pass only if Android exposes no shortcut metadata channel through `cmd shortcut` / `dumpsys shortcut` or exposes IDs without launchable ACTION_VIEW data fields, matching the spec implementation note.

## Open questions
- Gate-2 should confirm the Android `cmd package query-activities` output shape on the target API level; the check falls back to `dumpsys package` if that command is unavailable.
