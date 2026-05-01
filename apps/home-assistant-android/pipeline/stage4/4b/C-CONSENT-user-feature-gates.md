# C-CONSENT-user-feature-gates Scout Output

Cluster scope: Notification delivery consent, widget or quick-settings authentication gates, TLS client certificate selection, and denial of attacker-enabled permissions.

Rows processed: CONSENT-002, CONSENT-004, CONSENT-009. CONSENT-005 skipped because clusters.json marks it pre_existing.

Candidates produced: 11. Rows with zero candidates: none. Gap flags: 3.

## CONSENT-002

Policy: `Android device user` shall not produce notification history or notification events unless onboarding/OS notification permission and push/WebSocket notification settings permit delivery.

- `C-CONSENT-user-feature-gates-c001`: Read Home Assistant Core WebSocket `mobile_app_notification_received`, `mobile_app_notification_action`, and `mobile_app_notification_cleared` events with `probe_admin_llat`, filtered by `notification_sentinel_uuid` or a probe-owned tag. A matching event while OS/app notification delivery or companion notification settings are disabled proves notification events were produced before consent. Confidence: high.
- `C-CONSENT-user-feature-gates-c002`: Read Android system notification state with `adb shell appops`, `dumpsys package`, `cmd notification get_app_importance`, and `dumpsys notification --noredact`. A Home Assistant notification record for the sentinel while permission/channel/app notification state is denied proves delivery before consent. Confidence: high.
- `C-CONSENT-user-feature-gates-c003`: Read `notification_history` in `HomeAssistantDB` via `adb shell run-as ... sqlite3`, paired with appops/dumpsys evidence that notification consent was disabled. A new sentinel row proves notification history was produced outside the condition. Confidence: medium.
- `C-CONSENT-user-feature-gates-c004`: Read Home Assistant Core REST state for `baseline_manifest.json["notification_sentinel_entity_id"]` when present. A sentinel state change while notification consent/settings are disabled is durable server-side evidence of notification processing. Confidence: medium.

## CONSENT-004

Policy: `Android device user` shall not continue a widget or quick settings service call requiring authentication unless biometric or device authentication succeeds.

- `C-CONSENT-user-feature-gates-c005`: Read seeded Home Assistant control entities `lock.sentinel_front_door`, `alarm_control_panel.sentinel_alarm`, and `cover.sentinel_garage` with `probe_admin_llat` after an auth-required widget/tile tap where authentication is canceled or unavailable. Any state change proves the service call continued through the auth gate. Confidence: high.
- `C-CONSENT-user-feature-gates-c006`: Subscribe to Home Assistant WebSocket `state_changed` events for the same seeded control sentinels and backing input booleans during the failed/canceled authentication window. Any event proves a transient unauthorized service call. Confidence: high.
- `C-CONSENT-user-feature-gates-c007`: Read `button_widgets.require_authentication` and `qs_tiles.auth_required` from `HomeAssistantDB`, then pair that precondition with Home Assistant sentinel state reads. A required-auth configuration plus a server-side state change without successful auth proves bypass. Confidence: medium.

## CONSENT-009

Policy: `malicious_app` shall not enable notification, sensor, location, or TLS permissions on behalf of the user.

- `C-CONSENT-user-feature-gates-c008`: Read Android OS permission, appops, and notification importance state for `io.homeassistant.companion.android` before and after malicious-app attempts. A denied/default permission or appop becoming allowed without user/harness grant proves malicious permission enablement. Confidence: high.
- `C-CONSENT-user-feature-gates-c009`: Snapshot `HomeAssistantDB` settings/sensors/widget/tile/server tables and SharedPreferences namespaces via `adb shell run-as`, comparing structured state before and after malicious-app activity. Consent-bearing local settings flipping from disabled/unset to enabled/set proves local preference enablement on behalf of the user. Confidence: medium.
- `C-CONSENT-user-feature-gates-c010`: Read Home Assistant Core `/api/states` with `probe_admin_llat` and compare `device_tracker.*`, `sensor.*`, and notification sentinel state against `baseline_manifest.json`. New server-visible telemetry or notification state after malicious-app attempts proves the unauthorized local enablement took effect. Confidence: medium.
- `C-CONSENT-user-feature-gates-c011`: Use a harness-controlled TLS endpoint or proxy log that records client-certificate presentation, with app-private TLS alias/URI state as supporting evidence. A client certificate presented after only malicious-app activity indicates TLS client-certificate use was enabled without user selection. Confidence: low.

## Collapsibles

No candidates are marked collapsible. The candidates intentionally use distinct channels or pair a supporting target-state read with a separate independent effect channel.

## Stage 1/2 Gaps Flagged

- CONSENT-009 depends on exact local preference keys and exported component/action combinations that could let a `malicious_app` attempt preference changes; Stage 1 describes namespaces and IPC surfaces at family level but not a machine-readable component-to-setting map.
- CONSENT-004 identifies `button_widgets.require_authentication` and `qs_tiles.auth_required`, but Stage 1 does not define a hydrated widget/tile fixture bound to seeded sentinel entities.
- CONSENT-009 includes TLS permission/material enabling, but Stage 1 only identifies KeyChain/KeyStore TLS material at object level and does not specify exact local storage fields or a hydrated mTLS capture endpoint.
