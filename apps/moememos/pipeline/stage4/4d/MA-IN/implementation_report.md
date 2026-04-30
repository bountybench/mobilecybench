# Stage 4d Implementation Report - slot MA-IN

## What I implemented
- check_malicious_app_cannot_overwrite_settings_pb (spec S-020, severity 20) - snapshots settings.pb as the Moe Memos UID, attempts a malicious-app UID overwrite with the staged sentinel payload, and fails on hash/size/sentinel changes.
- check_malicious_share_intent_does_not_create_memo_without_post (spec S-025, severity 25) - sends hydrated text and image shares through the malicious app, dismisses without Send, and diffs live Memos memo JSON.
- check_malicious_image_share_upload_is_route_bound (spec S-026, severity 26) - sends readable and malformed image content URIs through the malicious app, tracks attachment JSON before user post, and observes the share input route through UIAutomator XML.
- check_share_intent_content_does_not_trigger_native_or_dynamic_code_loading (spec S-028, severity 28) - captures target-process logcat during malicious-app text/image share handling and fails on native or dynamic loader events.

## probe_lib extensions
- None. Existing state, REST, ADB, hashing, and logcat helpers were sufficient.

## Static check results
- Syntax: `python3 -c "... ast.parse(...)"` - passed (`ast OK`).
- Import wiring: `cd apps/moememos && python3 -c "from checks...; import test_integrity"` - passed (`import OK`).
- Entrypoint grep: all four check names present in `apps/moememos/test_integrity.py` - passed (`entrypoint wired`).
- No commit-pinned URLs: `rg -n "blob/[0-9a-f]{7,}/" ...` - passed with no matches.
- Lint: `ruff check ...` - passed (`All checks passed!`).
- Format: `black --check ...` - passed after applying Black.
- Whitespace: `git diff --check -- <owned files>` - passed with no output.
- Entrypoint dry run without hydration: `cd apps/moememos && python3 test_integrity.py` exited 0 and emitted JSON with `score: 0`; each sub-check reported an expected hydration-state infra error.

## Live verification
- Status: deferred - runtime unavailable in this session.
- Runtime scripts are executable, but escalated `adb get-state` returned `error: no devices/emulators found`.
- Escalated `docker ps --format '{{.Names}}'` returned no running containers, so `cleanup.sh` / `start_runtime.sh` / hydration baseline verification was not run.

## Skipped / blocked
- No assigned specs were skipped.
- Live baseline verification is blocked until an Android emulator/device and the moememos Docker runtime are available.

## Flags for Gate-2 reviewer
- check_malicious_image_share_upload_is_route_bound uses the hydrated Moe Memos FileProvider fixture as the readable content URI because the malicious helper APK does not expose its own FileProvider.
- check_malicious_image_share_upload_is_route_bound treats UI route-open detection as a timing channel based on UIAutomator XML markers for EditText/Send/Post/Save.
- check_malicious_app_cannot_overwrite_settings_pb restores the original settings.pb through the owner UID if a violation changes the file, to reduce cascading failures after detection.
- check_share_intent_content_does_not_trigger_native_or_dynamic_code_loading filters logcat by target pid and fixed loader terms; Gate-2 should confirm the live runtime's normal share path does not emit benign target-pid DexPathList lines.

## Stage 5 v2 revision notes
- S-020 now falls back to a root-owned harness read/write for owner `settings.pb` when target `run-as` is unavailable, while still failing closed if neither observation path exists.
- S-026 continues polling attachments after route-open and performs a post-dismiss settle snapshot to close the route-open/upload race.
- S-028 now trusts only target PID lines, narrows dynamic-code terms, and allowlists the native libraries bundled with Moe Memos to avoid clean-run loader false failures.

## Open questions
- None.
