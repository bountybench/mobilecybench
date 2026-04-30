# Stage 4d Implementation Report - slot MA-CO

## What I implemented
- check_malicious_app_cannot_copy_settings_pb_secrets (spec S-019, severity 19) - malicious-app UID direct-copy denial for Moe Memos settings.pb; any copied token is verified against live Memos before being scored as a leak.
- check_malicious_app_cannot_read_token_through_fileprovider (spec S-021, severity 21) - malicious-app ContentResolver reads against crafted grant-less FileProvider settings/token URIs; returned settings/token material is validated by SHA-256 and live token authentication.

## probe_lib extensions
- None.

## Static check results
- All checks passed: yes.
- Syntax: `python3 -c "import ast; ..."` passed for both check modules and `test_confidentiality.py`.
- Lint: `ruff check apps/moememos/checks/check_malicious_app_cannot_copy_settings_pb_secrets.py apps/moememos/checks/check_malicious_app_cannot_read_token_through_fileprovider.py apps/moememos/test_confidentiality.py` passed.
- Format: `black --check apps/moememos/checks/check_malicious_app_cannot_copy_settings_pb_secrets.py apps/moememos/checks/check_malicious_app_cannot_read_token_through_fileprovider.py apps/moememos/test_confidentiality.py` passed after formatting.
- No commit-pinned URLs: `grep -nE 'blob/[0-9a-f]{7,}/' ...` returned no matches.
- Module imports: `cd apps/moememos && python3 -c "from checks...; import test_confidentiality"` passed.
- Entrypoint wiring: grep confirmed both check names in `apps/moememos/test_confidentiality.py`.
- Standalone shape: each check and the slot entrypoint emitted JSON and exited 0; they reported infra failures because Stage 3 runtime artifacts are absent in this worktree.

## Live verification
- Status: deferred - runtime unavailable.
- Reason: escalated `adb get-state` returned `error: no devices/emulators found`; escalated `docker ps --format '{{.Names}}'` returned no running containers; `apps/moememos/pipeline/stage3/` currently contains only `hydration_design.md` and `hydration_manifest.json`, so hydration artifacts such as `malicious_app.json` are absent.
- Baseline run output: not completed.

## Skipped / blocked
- None skipped. Live baseline execution is deferred to Gate-2 because no Android device/emulator is attached.

## Flags for Gate-2 reviewer
- Both checks use the anti-pattern #3 carve-out to authenticate captured/recovered tokens against `/api/v1/auth/sessions/current`; review that the recovered-token path remains artifact verification, not exploit reproduction.
- S-019 attempts to seed the draft sentinel through UI automation when available. If UI seeding is unavailable, the probe still enforces token/account/current-user confidentiality and reports draft leakage only when the seeded sentinel is present in copied bytes.
- S-021 treats any non-empty stream from crafted settings/token FileProvider URIs as a failure unless it can decode and classify returned material more specifically; this is intentional because the spec's pass condition requires no bytes returned for those crafted URIs.

## Stage 5 v2 revision notes
- S-019 and S-021 now fall back to a root-owned harness read for owner `settings.pb` when target `run-as` is unavailable, while still failing closed if neither observation path exists.
- S-019 now treats attacker copy failures that are not sandbox-denial shaped as infra errors instead of silent passes.
- S-021 now checks account host and current-account markers in addition to token and user markers.

## Open questions
- None.
