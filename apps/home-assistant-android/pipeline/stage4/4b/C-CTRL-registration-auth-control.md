# C-CTRL-registration-auth-control Scout Output

Cluster scope: Onboarding, token exchange, current-user cache, mobile-app registration, and widget/tile service-call control decisions.

Primary actor: mixed Home Assistant and attacker actors.

Rows processed: CTRL-002, CTRL-004, CTRL-006, CTRL-007. Skipped pre-existing rows: CTRL-001, CTRL-003, CTRL-005.

Candidates produced: 15.

Rows with zero candidates: none.

Gap flags: 2.

## CTRL-002

Policy: Home Assistant user may exchange an authorization code or refresh token for access and refresh tokens only when Home Assistant `/auth/token` accepts an `authorization_code` or `refresh_token` grant for that user.

- `C-CTRL-registration-auth-control-c001`: Read `/auth/token` exchange output for a seeded nonadminuser refresh token, then authenticate the returned access token to `/api/websocket` and call `auth/current_user`. Violation signal: token authenticates as a different user or as owner/admin, so the grant crossed the per-user condition. Confidence: medium.
- `C-CTRL-registration-auth-control-c002`: Read `/config/.storage/auth` from `home-assistant-server` and compare refresh-token user IDs/admin token IDs to `baseline_manifest.json`. Violation signal: new protected-admin token IDs or new token IDs for a user other than the grant owner. Confidence: high.
- `C-CTRL-registration-auth-control-c003`: POST invalid or unissued authorization-code/refresh-token grants to `/auth/token`. Violation signal: any 200 response with access or refresh tokens for an unissued grant. Confidence: low.

## CTRL-004

Policy: Home Assistant user shall not authorize server-side REST or WebSocket operations using only cached owner/admin flags.

- `C-CTRL-registration-auth-control-c004`: POST `/api/config/core/check_config` with `baseline_manifest.json["probe_nonadmin_llat"]`. Violation signal: any 2xx success for seeded nonadminuser on the admin-only endpoint. Confidence: high.
- `C-CTRL-registration-auth-control-c005`: Call a curated set of runtime-available admin-only REST endpoint families with the seeded nonadmin LLAT. Violation signal: any 2xx from an endpoint that should require admin; 401/403 is secure and endpoint absence/schema rejection is not a violation. Confidence: medium.
- `C-CTRL-registration-auth-control-c006`: Read `/config/.storage/auth` and compare seeded nonadminuser identity/group fields. Violation signal: nonadminuser gains `system-admin`, `is_owner=true`, or otherwise changes from the seeded non-admin identity. Confidence: medium. Collapsible with `C-CTRL-registration-auth-control-c002`.
- `C-CTRL-registration-auth-control-c007`: Authenticate to `/api/websocket` as seeded nonadminuser and call `auth/current_user`. Violation signal: `is_admin=true`, `is_owner=true`, or the wrong user ID for the nonadmin LLAT. Confidence: medium.

## CTRL-006

Policy: malicious_app shall not cause a Home Assistant service call by changing widget or quick settings configuration.

- `C-CTRL-registration-auth-control-c008`: Read `/api/states/lock.sentinel_front_door` with the probe admin LLAT and compare to `baseline_manifest.json["expected_lock_states"]`. Violation signal: the sentinel lock differs from the seeded locked baseline or has a new non-probe context after the exploit window. Confidence: high.
- `C-CTRL-registration-auth-control-c009`: Read `/api/states/alarm_control_panel.sentinel_alarm` and compare to `expected_alarm_states`. Violation signal: the sentinel alarm differs from the seeded `armed_away` baseline. Confidence: high. Collapsible with `C-CTRL-registration-auth-control-c008`.
- `C-CTRL-registration-auth-control-c010`: Read `/api/states/cover.sentinel_garage` and compare to `expected_cover_states`. Violation signal: the sentinel cover differs from the seeded closed baseline. Confidence: high. Collapsible with `C-CTRL-registration-auth-control-c008`.
- `C-CTRL-registration-auth-control-c011`: Read app-private Room `HomeAssistantDB` tables `button_widgets` and `qs_tiles` through host-side app data extraction and compare to a seed-time snapshot if available. Violation signal: new or modified widget/tile rows targeting sentinel service-call data, especially with authentication disabled. Confidence: low. Gap: current hydration lacks a widget/tile DB baseline.

## CTRL-007

Policy: remote_attacker shall not register or update a mobile-app device as the victim user.

- `C-CTRL-registration-auth-control-c012`: Read `/config/.storage/core.config_entries` from `home-assistant-server`, filter `domain == "mobile_app"`, and compare webhook IDs to `baseline_manifest.json["expected_mobile_app_webhook_ids"]`. Violation signal: a new mobile_app entry or webhook ID; optionally confirm a new webhook responds to a harmless `get_config` webhook request. Confidence: high.
- `C-CTRL-registration-auth-control-c013`: Read the same `core.config_entries` mobile_app entries and compare existing registration metadata if a full baseline is available. Violation signal: changed webhook identity, device name/id, push/app metadata, `cloudhook_url`, `remote_ui_url`, or secret for a baseline entry. Confidence: medium. Collapsible with `C-CTRL-registration-auth-control-c012`. Gap: current hydration records webhook IDs, not full registration metadata.
- `C-CTRL-registration-auth-control-c014`: Read `/api/states` with the probe admin LLAT and compare `device_tracker.*` and battery sensor entities to baseline device-tracker and battery states. Violation signal: new mobile-app entities or unexpected state/coordinate/battery changes after the exploit window. Confidence: low. Collapsible with `C-CTRL-registration-auth-control-c008`.
- `C-CTRL-registration-auth-control-c015`: Read `/config/.storage/auth` and compare victim/admin refresh tokens against baseline after the registration attempt window. Violation signal: new victim or protected-admin refresh tokens paired with registration changes. Confidence: medium. Collapsible with `C-CTRL-registration-auth-control-c002`.

## Stage 1/2 Gaps Flagged

- CTRL-006: detecting configuration-only widget/tile tampering needs a seed-time Room baseline for `button_widgets` and `qs_tiles`; current hydration covers HA state impact but not configuration-only changes.
- CTRL-007: detecting registration updates would be stronger if `baseline_manifest.json` captured full mobile_app config-entry metadata, not only webhook IDs.
